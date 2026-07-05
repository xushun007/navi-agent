from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .models import Message, ToolCall


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

    @property
    def compressed(self) -> bool:
        return self.compressed_message_count > 0


class ContextEngine:
    def __init__(
        self,
        *,
        context_limit_tokens: int = 32_000,
        reserved_output_tokens: int = 4_000,
        compression_threshold_ratio: float = 0.75,
        protect_first_messages: int = 3,
        tail_budget_ratio: float = 0.25,
        chars_per_token: int = 4,
        max_summary_chars: int = 6_000,
        max_item_chars: int = 500,
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
        self._max_summary_chars = max_summary_chars
        self._max_item_chars = max_item_chars

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
            )

        middle = original[compress_start:tail_start]
        summary = Message(
            role="system",
            content=self._build_checkpoint_summary(
                middle=middle,
                latest_user_message=self._latest_user_message(original, start=head_end),
            ),
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

    def _build_checkpoint_summary(self, *, middle: list[Message], latest_user_message: Message | None) -> str:
        prior_summaries = [
            self._summarize_existing_summary(message)
            for message in middle
            if self._is_context_summary(message)
        ]
        source_messages = [
            message
            for message in middle
            if not self._is_context_summary(message)
        ]
        user_inputs = [message.content for message in source_messages if message.role == "user" and message.content.strip()]
        assistant_actions = [
            self._summarize_assistant(message)
            for message in source_messages
            if message.role == "assistant" and (message.content.strip() or message.tool_calls)
        ]
        tool_results = [
            self._summarize_tool_result(message)
            for message in source_messages
            if message.role == "tool"
        ]
        constraints = self._extract_constraints(user_inputs)
        references = self._extract_references(source_messages)

        lines = [
            SUMMARY_PREFIX,
            "Older middle conversation turns were compacted into this checkpoint. Treat it as historical context, not as a new user request.",
            "",
            "## Prior Context Summary",
            *self._bullet_lines(prior_summaries, empty="None."),
            "",
            "## Active Task",
            self._truncate(latest_user_message.content if latest_user_message else "None."),
            "",
            "## User Inputs Preserved",
            *self._bullet_lines(user_inputs, empty="None."),
            "",
            "## Completed Actions",
            *self._bullet_lines(assistant_actions, empty="None."),
            "",
            "## Tool Results",
            *self._bullet_lines(tool_results, empty="None."),
            "",
            "## Decisions and Constraints",
            *self._bullet_lines(constraints, empty="None."),
            "",
            "## Open Items",
            "Use the latest preserved user message below this summary as the source of truth. Historical asks above are stale unless the latest user message explicitly reactivates them.",
            "",
            "## Relevant Files and Commands",
            *self._bullet_lines(references, empty="None."),
            "",
            "--- END OF CONTEXT SUMMARY — respond to the latest user message after this summary ---",
        ]
        summary = "\n".join(lines).strip()
        if len(summary) <= self._max_summary_chars:
            return summary
        return summary[: self._max_summary_chars - 35].rstrip() + "\n...[summary truncated]"

    @staticmethod
    def _is_context_summary(message: Message) -> bool:
        return message.role == "system" and message.content.lstrip().startswith(SUMMARY_PREFIX)

    def _summarize_existing_summary(self, message: Message) -> str:
        content = message.content.replace(SUMMARY_PREFIX, "", 1).strip()
        content = re.sub(r"--- END OF CONTEXT SUMMARY.*$", "", content, flags=re.DOTALL).strip()
        return self._truncate(content)

    def _summarize_assistant(self, message: Message) -> str:
        parts = []
        if message.content.strip():
            parts.append(self._truncate(message.content))
        if message.tool_calls:
            tool_names = ", ".join(tool_call.name for tool_call in message.tool_calls)
            parts.append(f"Called tool(s): {tool_names}")
        return " — ".join(parts)

    def _summarize_tool_result(self, message: Message) -> str:
        label = f"tool_result:{message.tool_call_id}" if message.tool_call_id else "tool_result"
        return f"{label}: {self._truncate(message.content)}"

    def _extract_constraints(self, user_inputs: list[str]) -> list[str]:
        markers = (
            "must",
            "should",
            "prefer",
            "不要",
            "不能",
            "需要",
            "必须",
            "简洁",
            "标准",
            "不要问",
        )
        return [
            self._truncate(text)
            for text in user_inputs
            if any(marker in text for marker in markers)
        ][:8]

    def _extract_references(self, messages: list[Message]) -> list[str]:
        found: list[str] = []
        pattern = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|md|json|jsonl|toml|yaml|yml|txt)|`[^`]+`)")
        for message in messages:
            text = message.content or ""
            for match in pattern.findall(text):
                item = match.strip("`")
                if item and item not in found:
                    found.append(item)
                if len(found) >= 12:
                    return found
            for tool_call in message.tool_calls:
                for item in self._tool_call_references(tool_call):
                    if item not in found:
                        found.append(item)
                    if len(found) >= 12:
                        return found
        return found

    @staticmethod
    def _tool_call_references(tool_call: ToolCall) -> list[str]:
        references = []
        for key in ("path", "file", "command", "cwd"):
            value = tool_call.arguments.get(key)
            if isinstance(value, str) and value.strip():
                references.append(value.strip())
        return references

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

    def _bullet_lines(self, items: list[str], *, empty: str) -> list[str]:
        if not items:
            return [empty]
        return [f"- {self._truncate(item)}" for item in items[:12]]

    def _truncate(self, text: str) -> str:
        compact = " ".join(str(text or "").split())
        if len(compact) <= self._max_item_chars:
            return compact or "None."
        return compact[: self._max_item_chars].rstrip() + "...<truncated>"
