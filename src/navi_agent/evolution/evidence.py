from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from navi_agent.runtime import Message
from navi_agent.telemetry import RuntimeTrace


@dataclass(frozen=True, slots=True)
class SkillReviewEvidence:
    traces: list[RuntimeTrace]
    messages_snapshot: list[Message]

    @property
    def latest_trace(self) -> RuntimeTrace:
        return self.traces[-1]


def coerce_skill_review_evidence(
    trace: RuntimeTrace | SkillReviewEvidence,
) -> SkillReviewEvidence:
    if isinstance(trace, SkillReviewEvidence):
        return trace
    return SkillReviewEvidence(
        traces=[trace],
        messages_snapshot=[],
    )


def render_skill_review_evidence(
    evidence: SkillReviewEvidence,
) -> str:
    return _render_messages_snapshot(evidence.messages_snapshot)


def _render_messages_snapshot(messages: list[Message]) -> str:
    blocks = []
    for index, message in enumerate(messages, start=1):
        parts = [
            f"## Message {index}",
            f"role: {message.role}",
        ]
        if message.tool_call_id:
            parts.append(f"tool_call_id: {message.tool_call_id}")
        if message.tool_calls:
            parts.extend(
                [
                    "tool_calls:",
                    _indent(
                        _json_dumps(
                            [
                                {
                                    "id": tool_call.id,
                                    "name": tool_call.name,
                                    "arguments": tool_call.arguments,
                                }
                                for tool_call in message.tool_calls
                            ]
                        ),
                        prefix="  ",
                    ),
                ]
            )
        parts.extend(["content:", _indent(message.content, prefix="  ")])
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)

def _json_dumps(value: Any) -> str:
    if not value:
        return "{}"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _indent(value: str, *, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in value.splitlines())
