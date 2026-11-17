from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Protocol

from ..models import ContextCompactionCheckpoint, Message, ModelResponse, ToolCall
from ..transports.base import ModelRequest, ModelTransport


SUMMARY_PREFIX = "[Context Summary]"
_DENSE_TEXT = re.compile("[\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")


class ContextLimitError(RuntimeError):
    """Context could not be reduced below the configured input budget."""


@dataclass(frozen=True, slots=True)
class ContextSummaryCall:
    response: ModelResponse
    started_at: str
    completed_at: str
    duration_ms: int


@dataclass(slots=True)
class ContextBuildResult:
    messages: list[Message]
    original_message_count: int
    estimated_tokens_before: int
    estimated_tokens_after: int
    threshold_tokens: int
    compressed_message_count: int = 0
    protected_head_count: int = 0
    protected_tail_count: int = 0
    latest_user_anchored: bool = False
    summary_status: str = "not_needed"
    checkpoint: ContextCompactionCheckpoint | None = None
    summary_call: ContextSummaryCall | None = None

    @property
    def compressed(self) -> bool:
        return self.compressed_message_count > 0


class ContextEngine:
    def __init__(
        self,
        *,
        context_limit_tokens: int = 200_000,
        reserved_output_tokens: int = 4_000,
        compression_threshold_ratio: float = 0.75,
        protect_first_messages: int = 3,
        tail_budget_ratio: float = 0.25,
        chars_per_token: int = 4,
        summarizer: ContextSummarizer | None = None,
    ) -> None:
        if context_limit_tokens <= 0:
            raise ValueError("context_limit_tokens must be positive")
        if reserved_output_tokens < 0:
            raise ValueError("reserved_output_tokens must not be negative")
        if reserved_output_tokens >= context_limit_tokens:
            raise ValueError("reserved_output_tokens must be smaller than context_limit_tokens")
        if not 0 < compression_threshold_ratio <= 1:
            raise ValueError("compression_threshold_ratio must be in (0, 1]")
        if protect_first_messages < 0:
            raise ValueError("protect_first_messages must not be negative")
        if not 0 < tail_budget_ratio <= 1:
            raise ValueError("tail_budget_ratio must be in (0, 1]")
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")

        usable_input_tokens = max(1, context_limit_tokens - reserved_output_tokens)
        self.input_limit_tokens = usable_input_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self._threshold_tokens = max(1, int(usable_input_tokens * compression_threshold_ratio))
        self._tail_budget_tokens = max(1, int(self._threshold_tokens * tail_budget_ratio))
        self._protect_first_messages = protect_first_messages
        self._chars_per_token = chars_per_token
        self._summarizer = summarizer

    def build(
        self,
        messages: list[Message],
        checkpoint: ContextCompactionCheckpoint | None = None,
        *,
        prefix_messages: list[Message] | None = None,
        tools: list[dict[str, object]] | None = None,
    ) -> ContextBuildResult:
        original = list(messages)
        prefix = list(prefix_messages or ())
        tool_tokens = self.estimate_tool_tokens(tools or [])
        estimated_before = self.estimate_tokens([*prefix, *original]) + tool_tokens
        reusable = self._materialize_checkpoint(original, checkpoint)
        history = original if reusable is None else reusable
        estimated_current = self.estimate_tokens([*prefix, *history]) + tool_tokens
        head_end = self._protect_head_end(history)
        compress_start = self._align_start_forward(history, head_end)
        tail_start, latest_user_anchored = self._find_tail_start(history, compress_start)
        source_tail_start = tail_start
        if reusable is not None:
            assert checkpoint is not None
            source_tail_start = (
                checkpoint.covered_message_count
                + tail_start - checkpoint.protected_head_count - 1
            )
            # Recompress only when new history can be covered. A large fixed prefix
            # must not cause the same summary to be regenerated on every tool step.
            if (estimated_current <= self._threshold_tokens
                    or source_tail_start <= checkpoint.covered_message_count):
                return ContextBuildResult(
                    messages=self._sanitize_tool_pairs([*prefix, *reusable]),
                    original_message_count=len(original),
                    estimated_tokens_before=estimated_before,
                    estimated_tokens_after=estimated_current,
                    threshold_tokens=self._threshold_tokens,
                    compressed_message_count=(
                        checkpoint.covered_message_count - checkpoint.protected_head_count
                    ),
                    protected_head_count=checkpoint.protected_head_count,
                    protected_tail_count=len(original) - checkpoint.covered_message_count,
                    latest_user_anchored=True,
                    summary_status="checkpoint_reused",
                )
        if estimated_current <= self._threshold_tokens:
            return ContextBuildResult(
                messages=self._sanitize_tool_pairs([*prefix, *original]),
                original_message_count=len(original),
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_before,
                threshold_tokens=self._threshold_tokens,
            )

        if compress_start >= tail_start:
            return ContextBuildResult(
                messages=self._sanitize_tool_pairs([*prefix, *history]),
                original_message_count=len(original),
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_current,
                threshold_tokens=self._threshold_tokens,
                protected_head_count=head_end,
                protected_tail_count=max(0, len(original) - source_tail_start),
                latest_user_anchored=latest_user_anchored,
                summary_status="not_needed",
            )

        if self._summarizer is None:
            return ContextBuildResult(
                messages=self._sanitize_tool_pairs([*prefix, *history]),
                original_message_count=len(original),
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_current,
                threshold_tokens=self._threshold_tokens,
                protected_head_count=compress_start,
                protected_tail_count=max(0, len(original) - source_tail_start),
                latest_user_anchored=latest_user_anchored,
                summary_status="missing_summarizer",
            )

        middle = history[compress_start:tail_start]
        summary_call = self._summarizer.summarize(
            middle=middle,
            latest_user_message=self._latest_user_message(history, start=head_end),
        )
        summary = Message(
            role="runtime",
            content=self._normalize_summary(summary_call.response.content),
        )
        compacted = [
            *history[:compress_start],
            summary,
            *history[tail_start:],
        ]
        compacted = self._sanitize_tool_pairs(compacted)
        rendered = [*prefix, *compacted]
        estimated_after = self.estimate_tokens(rendered) + tool_tokens
        return ContextBuildResult(
            messages=rendered,
            original_message_count=len(original),
            estimated_tokens_before=estimated_before,
            estimated_tokens_after=estimated_after,
            threshold_tokens=self._threshold_tokens,
            compressed_message_count=source_tail_start - compress_start,
            protected_head_count=compress_start,
            protected_tail_count=max(0, len(original) - source_tail_start),
            latest_user_anchored=latest_user_anchored,
            summary_status="llm",
            summary_call=summary_call,
            checkpoint=ContextCompactionCheckpoint(
                session_id="",
                covered_message_count=source_tail_start,
                protected_head_count=compress_start,
                source_hash=self.source_hash(original[:source_tail_start]),
                summary=summary.content,
            ),
        )

    @classmethod
    def source_hash(cls, messages: list[Message]) -> str:
        payload = [
            {
                "role": message.role,
                "content": message.content,
                "reasoning_content": message.reasoning_content,
                "tool_call_id": message.tool_call_id,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    }
                    for tool_call in message.tool_calls
                ],
            }
            for message in messages
        ]
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _materialize_checkpoint(
        self,
        messages: list[Message],
        checkpoint: ContextCompactionCheckpoint | None,
    ) -> list[Message] | None:
        if checkpoint is None:
            return None
        if checkpoint.protected_head_count < 0 or checkpoint.covered_message_count <= 0:
            return None
        if checkpoint.covered_message_count > len(messages):
            return None
        if checkpoint.protected_head_count > checkpoint.covered_message_count:
            return None
        covered = messages[: checkpoint.covered_message_count]
        if self.source_hash(covered) != checkpoint.source_hash:
            return None
        # Keep indices aligned with the durable transcript until boundaries are
        # mapped back to source offsets. Sanitize only the final request.
        return [
            *messages[: checkpoint.protected_head_count],
            Message(role="runtime", content=checkpoint.summary),
            *messages[checkpoint.covered_message_count :],
        ]

    def estimate_tokens(self, messages: list[Message]) -> int:
        return sum(self._estimate_message_tokens(message) for message in messages)

    def estimate_tool_tokens(self, tools: list[dict[str, object]]) -> int:
        if not tools:
            return 0
        # Include per-function wrapping and protocol overhead as well as schema text.
        return self._estimate_text_tokens(json.dumps(tools, ensure_ascii=False)) + 32 * len(tools)

    def validate_request(self, messages: list[Message], tools: list[dict[str, object]]) -> None:
        estimate = self.estimate_tokens(messages) + self.estimate_tool_tokens(tools)
        if estimate >= self.input_limit_tokens:
            raise ContextLimitError(
                f"Estimated input {estimate} tokens meets or exceeds the configured input budget "
                f"{self.input_limit_tokens} (including tool definitions)."
            )

    def _estimate_text_tokens(self, text: str) -> int:
        # CJK is token-dense; UTF-8 bytes also avoid undercounting other non-ASCII scripts.
        sparse = text if text.isascii() else _DENSE_TEXT.sub("", text)
        dense_tokens = len(text) - len(sparse)
        byte_count = len(sparse.encode("utf-8", errors="replace"))
        return dense_tokens + (byte_count + self._chars_per_token - 1) // self._chars_per_token

    def _estimate_message_tokens(self, message: Message) -> int:
        parts = [message.role, message.content or ""]
        if message.role == "runtime":
            parts.append("[Runtime context]\n")
        if message.reasoning_content:
            parts.append(message.reasoning_content)
        if message.tool_call_id:
            parts.append(message.tool_call_id)
        for tool_call in message.tool_calls:
            parts.extend([tool_call.id, tool_call.name])
            try:
                parts.append(json.dumps(tool_call.arguments, ensure_ascii=False, sort_keys=True))
            except TypeError:
                parts.append(str(tool_call.arguments))
        return self._estimate_text_tokens("".join(parts)) + 12

    def _protect_head_end(self, messages: list[Message]) -> int:
        non_system_seen = 0
        head_end = 0
        for index, message in enumerate(messages):
            if self._is_context_summary(message):
                break
            if message.role == "system":
                head_end = index + 1
                continue
            if non_system_seen < self._protect_first_messages:
                non_system_seen += 1
                head_end = index + 1
                continue
            break
        return head_end

    def _find_tail_start(self, messages: list[Message], head_end: int) -> tuple[int, bool]:
        tail_start = len(messages)
        accumulated_tokens = 0
        for index in range(len(messages) - 1, head_end - 1, -1):
            next_tokens = self._estimate_message_tokens(messages[index])
            if tail_start < len(messages) and accumulated_tokens + next_tokens > self._tail_budget_tokens:
                break
            accumulated_tokens += next_tokens
            tail_start = index

        latest_user_index = self._latest_user_index(messages, start=head_end)
        anchored = latest_user_index is not None and latest_user_index < tail_start
        if anchored:
            tail_start = latest_user_index

        return self._align_tail_backward(messages, tail_start, head_end), anchored

    @staticmethod
    def _latest_user_index(messages: list[Message], *, start: int) -> int | None:
        for index in range(len(messages) - 1, start - 1, -1):
            if messages[index].role == "user":
                return index
        return None

    def _latest_user_message(self, messages: list[Message], *, start: int) -> Message | None:
        index = self._latest_user_index(messages, start=start)
        return messages[index] if index is not None else None

    @staticmethod
    def _align_start_forward(messages: list[Message], index: int) -> int:
        while index < len(messages) and messages[index].role == "tool":
            index += 1
        return index

    @staticmethod
    def _align_tail_backward(messages: list[Message], index: int, head_end: int) -> int:
        if index <= head_end or index >= len(messages):
            return index
        scan = index
        while scan > head_end and messages[scan].role == "tool":
            scan -= 1
        if messages[scan].role == "assistant" and messages[scan].tool_calls:
            return scan
        return index

    @staticmethod
    def _is_context_summary(message: Message) -> bool:
        return message.role in {"system", "runtime"} and message.content.lstrip().startswith(SUMMARY_PREFIX)

    @staticmethod
    def _normalize_summary(summary: str) -> str:
        content = summary.strip()
        if content.startswith(SUMMARY_PREFIX):
            return content
        return f"{SUMMARY_PREFIX}\n{content}"

    def _sanitize_tool_pairs(self, messages: list[Message]) -> list[Message]:
        result: list[Message] = []
        pending_call_ids: set[str] = set()
        for message in messages:
            if message.role == "tool":
                if message.tool_call_id in pending_call_ids:
                    result.append(message)
                    pending_call_ids.remove(message.tool_call_id)
                continue
            if pending_call_ids:
                result.extend(
                    Message(
                        role="tool",
                        content="[Result from earlier conversation — see context summary above]",
                        tool_call_id=tool_call_id,
                    )
                    for tool_call_id in sorted(pending_call_ids)
                )
                pending_call_ids.clear()
            result.append(message)
            if message.role == "assistant":
                pending_call_ids = {
                    tool_call.id for tool_call in message.tool_calls if tool_call.id
                }
        if pending_call_ids:
            result.extend(
                Message(
                    role="tool",
                    content="[Result from earlier conversation — see context summary above]",
                    tool_call_id=tool_call_id,
                )
                for tool_call_id in sorted(pending_call_ids)
            )
        return result

    def sanitize_tool_pairs(self, messages: list[Message]) -> list[Message]:
        """Return messages safe for providers that require adjacent tool pairs."""
        return self._sanitize_tool_pairs(messages)


class ContextSummarizer(Protocol):
    def summarize(
        self,
        *,
        middle: list[Message],
        latest_user_message: Message | None,
    ) -> ContextSummaryCall: ...


class LLMContextSummarizer:
    def __init__(self, transport: ModelTransport, *, context_limit_tokens: int = 200_000) -> None:
        self._transport = transport
        self._budget = ContextEngine(
            context_limit_tokens=context_limit_tokens,
            reserved_output_tokens=min(2_000, max(1, context_limit_tokens // 20)),
        )

    def summarize(
        self,
        *,
        middle: list[Message],
        latest_user_message: Message | None,
    ) -> ContextSummaryCall:
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        started_perf = perf_counter()
        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(
                role="user",
                content=self._build_summary_request(
                    middle=middle,
                    latest_user_message=latest_user_message,
                ),
            ),
        ]
        self._budget.validate_request(messages, [])
        response = self._transport.generate(
            ModelRequest(messages=messages, tools=[],
                         max_output_tokens=self._budget.reserved_output_tokens)
        )
        if response.finish_reason == "length" or response.tool_calls:
            raise RuntimeError("context summarizer returned an incomplete summary")
        summary = response.content.strip()
        if not summary:
            raise RuntimeError("context summarizer returned an empty summary")
        return ContextSummaryCall(
            response=response,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            duration_ms=int((perf_counter() - started_perf) * 1000),
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a context compression component for an engineering agent. "
            "Summarize the provided historical middle conversation so the next model call can continue coherently. "
            "Do not answer the active user request. Do not invent facts. Preserve concrete requirements, decisions, file paths, commands, errors, test results, tool outcomes, and open questions. "
            "If prior context summaries appear, merge them into one current summary instead of nesting or quoting them. "
            "Write in the user's language when clear."
        )

    def _build_summary_request(self, *, middle: list[Message], latest_user_message: Message | None) -> str:
        active_task = latest_user_message.content if latest_user_message else "None."
        return "\n".join(
            [
                "Compress the historical middle conversation into this exact shape:",
                "",
                SUMMARY_PREFIX,
                "## Current Goal",
                "<the durable goal and active task context>",
                "## User Requirements",
                "<requirements and preferences that still matter>",
                "## Decisions",
                "<important decisions and rejected options>",
                "## Completed Work",
                "<work already completed, including commits or validations>",
                "## Files Commands Errors",
                "<specific files, commands, errors, test results, external references>",
                "## Open Items",
                "<what remains unresolved>",
                "",
                "Rules:",
                "- Preserve meaning over wording.",
                "- Keep the latest user request as active input, not as historical work.",
                "- Mark stale historical requests as stale if superseded.",
                "- Merge any existing context summary into this one; do not include nested [Context Summary] blocks.",
                "- Output only the summary.",
                "",
                "Latest preserved user request after the summary:",
                active_task,
                "",
                "Historical middle conversation:",
                self._serialize_messages(middle),
            ]
        )

    @staticmethod
    def _serialize_messages(messages: list[Message]) -> str:
        chunks = []
        for index, message in enumerate(messages, start=1):
            parts = [f"<message index={index} role={message.role}>"]
            if message.tool_call_id:
                parts.append(f"tool_call_id: {message.tool_call_id}")
            if message.content:
                parts.append(message.content)
            if message.tool_calls:
                parts.append("tool_calls:")
                for tool_call in message.tool_calls:
                    parts.append(
                        json.dumps(
                            {
                                "id": tool_call.id,
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
            parts.append("</message>")
            chunks.append("\n".join(parts))
        return "\n\n".join(chunks)
