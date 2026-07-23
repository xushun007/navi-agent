from __future__ import annotations

from threading import Lock
from typing import Any

from navi_agent.events import RuntimeEvent

from .models import ModelCallTrace, RuntimeTrace, ToolExecutionTrace
from .store import TraceStore


class TraceBuilder:
    """Builds completed runtime traces solely from RuntimeEvent facts."""

    def __init__(self, store: TraceStore) -> None:
        self._store = store
        self._traces: dict[str, RuntimeTrace] = {}
        self._lock = Lock()

    def handle(self, event: RuntimeEvent) -> None:
        completed: RuntimeTrace | None = None
        with self._lock:
            if event.name == "runtime.started":
                self._traces[event.run_id] = RuntimeTrace(
                    trace_id=event.run_id,
                    session_id=event.session_id,
                    user_id=event.user_id,
                    user_message="",
                    final_response="",
                    status="running",
                    agent_role=_string(event.metadata.get("agent_role")) or "primary",
                    parent_session_id=_string(event.metadata.get("parent_session_id")),
                    started_at=_string(event.metadata.get("started_at")) or event.timestamp,
                )
                return

            trace = self._traces.get(event.run_id)
            if trace is None:
                return
            if event.name == "user.message":
                trace.user_message = _string(event.metadata.get("content")) or ""
            elif event.name == "runtime.context_ready":
                trace.system_prompt = _string(event.metadata.get("system_prompt"))
                trace.injected_skill_names = _string_list(
                    event.metadata.get("injected_skill_names")
                )
            elif event.name in {"model.response", "model.discarded"}:
                trace.model_calls.append(_model_call(event))
            elif event.name == "tool.result":
                trace.tool_executions.append(_tool_execution(event))
            elif event.name == "runtime.completed":
                _complete_trace(trace, event)
                completed = self._traces.pop(event.run_id)

        if completed is not None:
            self._store.record(completed)


def _model_call(event: RuntimeEvent) -> ModelCallTrace:
    usage = _mapping(event.metadata.get("usage"))
    tool_calls = event.metadata.get("tool_calls")
    tool_call_names = []
    if isinstance(tool_calls, list):
        tool_call_names = [
            name
            for item in tool_calls
            if isinstance(item, dict)
            if (name := _string(item.get("name"))) is not None
        ]
    return ModelCallTrace(
        iteration=event.iteration or 0,
        response_content=_string(event.metadata.get("content")) or "",
        tool_call_names=tool_call_names,
        reasoning_content=_string(event.metadata.get("reasoning_content")),
        started_at=_string(event.metadata.get("started_at")),
        completed_at=_string(event.metadata.get("completed_at")),
        duration_ms=_integer(event.metadata.get("duration_ms")),
        provider=_string(event.metadata.get("provider")),
        model=_string(event.metadata.get("model")),
        input_tokens=_integer(usage.get("input_tokens")),
        output_tokens=_integer(usage.get("output_tokens")),
        cache_read_tokens=_integer(usage.get("cache_read_tokens")),
        cache_write_tokens=_integer(usage.get("cache_write_tokens")),
        reasoning_tokens=_integer(usage.get("reasoning_tokens")),
        cost_usd=_number(usage.get("cost_usd")),
    )


def _tool_execution(event: RuntimeEvent) -> ToolExecutionTrace:
    metadata = _mapping(event.metadata.get("metadata"))
    structured_content = _mapping(event.metadata.get("structured_content"))
    return ToolExecutionTrace(
        iteration=event.iteration or 0,
        tool_call_id=_string(event.metadata.get("tool_call_id")) or event.item_id or "",
        tool_name=_string(event.metadata.get("tool_name")) or "",
        status=_string(event.metadata.get("status")) or "error",
        arguments=_mapping(event.metadata.get("arguments")),
        content=_string(event.metadata.get("content")) or "",
        metadata=metadata,
        structured_content=structured_content,
        approval_required=structured_content.get("approval_required") is True,
        error_category=_string(event.metadata.get("error_category")),
        error_type=_string(event.metadata.get("error_type")),
        error_message=_string(event.metadata.get("error_message")),
        retryable=_boolean(event.metadata.get("retryable")),
        http_status=_optional_integer(event.metadata.get("http_status")),
        started_at=_string(event.metadata.get("started_at")),
        completed_at=_string(event.metadata.get("completed_at")),
        duration_ms=_integer(event.metadata.get("duration_ms")),
    )


def _complete_trace(trace: RuntimeTrace, event: RuntimeEvent) -> None:
    trace.final_response = _string(event.metadata.get("final_response")) or ""
    trace.status = _string(event.metadata.get("status")) or "failed"
    trace.tool_names = [item.tool_name for item in trace.tool_executions]
    trace.total_iterations = len(trace.model_calls)
    trace.approval_count = sum(1 for item in trace.tool_executions if item.approval_required)
    trace.error_count = sum(1 for item in trace.tool_executions if item.status == "error")
    trace.error_category = _string(event.metadata.get("error_category"))
    trace.error_type = _string(event.metadata.get("error_type"))
    trace.error_message = _string(event.metadata.get("error_message"))
    trace.retryable = _boolean(event.metadata.get("retryable"))
    trace.http_status = _optional_integer(event.metadata.get("http_status"))
    trace.error_source = _string(event.metadata.get("error_source"))
    trace.attempt_count = _integer(event.metadata.get("attempt_count"))
    trace.completed_at = _string(event.metadata.get("completed_at")) or event.timestamp
    trace.duration_ms = _integer(event.metadata.get("duration_ms"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
