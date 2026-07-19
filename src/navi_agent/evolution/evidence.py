from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


@dataclass(frozen=True, slots=True)
class SkillReviewEvidence:
    traces: list[RuntimeTrace]

    @property
    def latest_trace(self) -> RuntimeTrace:
        return self.traces[-1]

    @property
    def tool_executions(self) -> list[ToolExecutionTrace]:
        executions: list[ToolExecutionTrace] = []
        for trace in self.traces:
            executions.extend(trace.tool_executions)
        return executions


@dataclass(frozen=True, slots=True)
class EvidenceRenderConfig:
    user_message_limit: int = 1200
    final_response_limit: int = 1200
    tool_arguments_limit: int = 300
    tool_output_limit: int = 900
    tool_output_head: int = 350
    tool_output_tail: int = 500
    error_message_limit: int = 500


def coerce_skill_review_evidence(
    trace: RuntimeTrace | SkillReviewEvidence,
) -> SkillReviewEvidence:
    if isinstance(trace, SkillReviewEvidence):
        return trace
    return SkillReviewEvidence(traces=[trace])


def render_skill_review_evidence(
    evidence: SkillReviewEvidence,
    *,
    config: EvidenceRenderConfig | None = None,
) -> str:
    render_config = config or EvidenceRenderConfig()
    blocks = []
    for index, trace in enumerate(evidence.traces, start=1):
        blocks.append(_render_trace(index, trace, config=render_config))
    return "\n\n".join(blocks)


def smart_truncate(
    value: Any,
    *,
    limit: int,
    head: int | None = None,
    tail: int | None = None,
) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ""

    marker = "\n...[truncated]...\n"
    available = max(limit - len(marker), 0)
    if available <= 0:
        return text[-limit:]

    if head is None or tail is None:
        tail = min(max(available // 2, 1), available)
        head = max(available - tail, 0)
    if head + tail > available:
        tail = min(tail, available)
        head = max(available - tail, 0)

    return f"{text[:head].rstrip()}{marker}{text[-tail:].lstrip()}"


def _render_trace(
    index: int,
    trace: RuntimeTrace,
    *,
    config: EvidenceRenderConfig,
) -> str:
    return "\n".join(
        [
            f"## Trace {index}",
            f"session_id: {trace.session_id}",
            f"trace_id: {trace.trace_id}",
            f"status: {trace.status}",
            f"user_message: {smart_truncate(trace.user_message, limit=config.user_message_limit)}",
            f"final_response: {smart_truncate(trace.final_response, limit=config.final_response_limit)}",
            "tool_executions:",
            _render_tool_executions(trace.tool_executions, config=config),
        ]
    )


def _render_tool_executions(
    executions: list[ToolExecutionTrace],
    *,
    config: EvidenceRenderConfig,
) -> str:
    if not executions:
        return "  - none"
    return "\n".join(_render_tool_execution(execution, config=config) for execution in executions)


def _render_tool_execution(
    execution: ToolExecutionTrace,
    *,
    config: EvidenceRenderConfig,
) -> str:
    lines = [
        f"  - tool: {execution.tool_name}",
        f"    status: {execution.status}",
        "    arguments: "
        + smart_truncate(
            _json_dumps(execution.arguments),
            limit=config.tool_arguments_limit,
        ),
    ]
    error_line = _render_error_line(execution, config=config)
    if error_line:
        lines.append(error_line)
    output = smart_truncate(
        execution.content,
        limit=config.tool_output_limit,
        head=config.tool_output_head,
        tail=config.tool_output_tail,
    )
    if output:
        lines.extend(["    output:", _indent(output, prefix="      ")])
    else:
        lines.append("    output: <empty>")
    return "\n".join(lines)


def _render_error_line(
    execution: ToolExecutionTrace,
    *,
    config: EvidenceRenderConfig,
) -> str:
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
        parts.append(
            "message="
            + smart_truncate(
                execution.error_message,
                limit=config.error_message_limit,
            )
        )
    if not parts:
        return ""
    return "    error: " + " ".join(parts)


def _json_dumps(value: dict[str, Any]) -> str:
    if not value:
        return "{}"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _indent(value: str, *, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in value.splitlines())
