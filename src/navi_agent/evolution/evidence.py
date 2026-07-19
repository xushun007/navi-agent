from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from navi_agent.runtime import Message
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


@dataclass(frozen=True, slots=True)
class SkillReviewEvidence:
    traces: list[RuntimeTrace]
    messages_snapshot: list[Message] = field(default_factory=list)

    @property
    def latest_trace(self) -> RuntimeTrace:
        return self.traces[-1]

    @property
    def tool_executions(self) -> list[ToolExecutionTrace]:
        executions: list[ToolExecutionTrace] = []
        for trace in self.traces:
            executions.extend(trace.tool_executions)
        return executions


def coerce_skill_review_evidence(
    trace: RuntimeTrace | SkillReviewEvidence,
) -> SkillReviewEvidence:
    if isinstance(trace, SkillReviewEvidence):
        return trace
    return SkillReviewEvidence(traces=[trace], messages_snapshot=[])


def render_skill_review_evidence(
    evidence: SkillReviewEvidence,
) -> str:
    if evidence.messages_snapshot:
        return _render_messages_snapshot(evidence.messages_snapshot)
    blocks = []
    for index, trace in enumerate(evidence.traces, start=1):
        blocks.append(_render_trace(index, trace))
    return "\n\n".join(blocks)


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


def _render_trace(index: int, trace: RuntimeTrace) -> str:
    return "\n".join(
        [
            f"## Trace {index}",
            f"session_id: {trace.session_id}",
            f"trace_id: {trace.trace_id}",
            f"status: {trace.status}",
            f"user_message: {trace.user_message}",
            f"final_response: {trace.final_response}",
            "tool_executions:",
            _render_tool_executions(trace.tool_executions),
        ]
    )


def _render_tool_executions(executions: list[ToolExecutionTrace]) -> str:
    if not executions:
        return "  - none"
    return "\n".join(_render_tool_execution(execution) for execution in executions)


def _render_tool_execution(execution: ToolExecutionTrace) -> str:
    lines = [
        f"  - tool: {execution.tool_name}",
        f"    status: {execution.status}",
        "    arguments: " + _json_dumps(execution.arguments),
    ]
    error_line = _render_error_line(execution)
    if error_line:
        lines.append(error_line)
    output = execution.content.strip()
    if output:
        lines.extend(["    output:", _indent(output, prefix="      ")])
    else:
        lines.append("    output: <empty>")
    return "\n".join(lines)


def _render_error_line(execution: ToolExecutionTrace) -> str:
    parts = []
    if execution.error_category:
        parts.append(f"category={execution.error_category}")
    if execution.error_type:
        parts.append(f"type={execution.error_type}")
    if execution.http_status is not None:
        parts.append(f"http_status={execution.http_status}")
    if execution.retryable is not None:
        parts.append(f"retryable={execution.retryable}")
    if execution.error_message:
        parts.append("message=" + execution.error_message)
    if not parts:
        return ""
    return "    error: " + " ".join(parts)


def _json_dumps(value: Any) -> str:
    if not value:
        return "{}"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _indent(value: str, *, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in value.splitlines())
