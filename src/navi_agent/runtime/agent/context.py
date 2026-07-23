from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from ..models import Message, ToolCall
from ..transports.base import ModelRequest, ModelTransport


SUMMARY_PREFIX = "[Context Summary]"


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

    @property
    def compressed(self) -> bool:
        return self.compressed_message_count > 0


class ContextEngine:
    def __init__(
        self,
        *,
        context_limit_tokens: int = 128_000,
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
        if not 0 < compression_threshold_ratio <= 1:
            raise ValueError("compression_threshold_ratio must be in (0, 1]")
        if protect_first_messages < 0:
            raise ValueError("protect_first_messages must not be negative")
        if not 0 < tail_budget_ratio <= 1:
            raise ValueError("tail_budget_ratio must be in (0, 1]")
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")

        usable_input_tokens = max(1, context_limit_tokens - reserved_output_tokens)
        self._threshold_tokens = max(1, int(usable_input_tokens * compression_threshold_ratio))
        self._tail_budget_tokens = max(1, int(self._threshold_tokens * tail_budget_ratio))
        self._protect_first_messages = protect_first_messages
        self._chars_per_token = chars_per_token
        self._summarizer = summarizer

    def build(self, messages: list[Message]) -> ContextBuildResult:
        original = list(messages)
        estimated_before = self.estimate_tokens(original)
        if estimated_before <= self._threshold_tokens:
            return ContextBuildResult(
                messages=original,
                original_message_count=len(original),
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_before,
                threshold_tokens=self._threshold_tokens,
            )

        head_end = self._protect_head_end(original)
        compress_start = self._align_start_forward(original, head_end)
        tail_start, latest_user_anchored = self._find_tail_start(original, compress_start)

        if compress_start >= tail_start:
            return ContextBuildResult(
                messages=original,
                original_message_count=len(original),
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_before,
                threshold_tokens=self._threshold_tokens,
                protected_head_count=head_end,
                protected_tail_count=max(0, len(original) - tail_start),
                latest_user_anchored=latest_user_anchored,
                summary_status="not_needed",
            )

        if self._summarizer is None:
            return ContextBuildResult(
                messages=original,
                original_message_count=len(original),
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_before,
                threshold_tokens=self._threshold_tokens,
                protected_head_count=compress_start,
                protected_tail_count=max(0, len(original) - tail_start),
                latest_user_anchored=latest_user_anchored,
                summary_status="missing_summarizer",
            )

        middle = original[compress_start:tail_start]
        summary_text = self._summarizer.summarize(
            middle=middle,
            latest_user_message=self._latest_user_message(original, start=head_end),
        )
        summary = Message(
            role="system",
            content=self._normalize_summary(summary_text),
        )
        compacted = [
            *original[:compress_start],
            summary,
            *original[tail_start:],
        ]
        compacted = self._sanitize_tool_pairs(compacted)
        estimated_after = self.estimate_tokens(compacted)
        return ContextBuildResult(
            messages=compacted,
            original_message_count=len(original),
            estimated_tokens_before=estimated_before,
            estimated_tokens_after=estimated_after,
            threshold_tokens=self._threshold_tokens,
            compressed_message_count=len(middle),
            protected_head_count=compress_start,
            protected_tail_count=max(0, len(original) - tail_start),
            latest_user_anchored=latest_user_anchored,
            summary_status="llm",
        )

    def estimate_tokens(self, messages: list[Message]) -> int:
        return sum(self._estimate_message_tokens(message) for message in messages)

    def _estimate_message_tokens(self, message: Message) -> int:
        chars = len(message.role) + len(message.content or "") + 12
        if message.reasoning_content:
            chars += len(message.reasoning_content)
        if message.tool_call_id:
            chars += len(message.tool_call_id)
        for tool_call in message.tool_calls:
            chars += len(tool_call.id) + len(tool_call.name)
            try:
                chars += len(json.dumps(tool_call.arguments, ensure_ascii=False, sort_keys=True))
            except TypeError:
                chars += len(str(tool_call.arguments))
        return max(1, chars // self._chars_per_token + 8)

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
        return message.role == "system" and message.content.lstrip().startswith(SUMMARY_PREFIX)

    @staticmethod
    def _normalize_summary(summary: str) -> str:
        content = summary.strip()
        if content.startswith(SUMMARY_PREFIX):
            return content
        return f"{SUMMARY_PREFIX}\n{content}"

    def _sanitize_tool_pairs(self, messages: list[Message]) -> list[Message]:
        assistant_call_ids = {
            tool_call.id
            for message in messages
            if message.role == "assistant"
            for tool_call in message.tool_calls
            if tool_call.id
        }
        tool_result_ids = {
            message.tool_call_id
            for message in messages
            if message.role == "tool" and message.tool_call_id
        }
        result: list[Message] = []
        for message in messages:
            if message.role == "tool" and message.tool_call_id not in assistant_call_ids:
                continue
            result.append(message)
            if message.role == "assistant":
                for tool_call in message.tool_calls:
                    if tool_call.id and tool_call.id not in tool_result_ids:
                        result.append(
                            Message(
                                role="tool",
                                content="[Result from earlier conversation — see context summary above]",
                                tool_call_id=tool_call.id,
                            )
                        )
        return result

class ContextSummarizer(Protocol):
    def summarize(self, *, middle: list[Message], latest_user_message: Message | None) -> str: ...


class LLMContextSummarizer:
    def __init__(self, transport: ModelTransport) -> None:
        self._transport = transport

    def summarize(self, *, middle: list[Message], latest_user_message: Message | None) -> str:
        response = self._transport.generate(
            ModelRequest(
                messages=[
                    Message(role="system", content=self._system_prompt()),
                    Message(
                        role="user",
                        content=self._build_summary_request(
                            middle=middle,
                            latest_user_message=latest_user_message,
                        ),
                    ),
                ],
                tools=[],
            )
        )
        summary = response.content.strip()
        if not summary:
            raise RuntimeError("context summarizer returned an empty summary")
        return summary

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
