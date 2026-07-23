from __future__ import annotations

from navi_agent.events import RuntimeEvent
from navi_agent.telemetry import InMemoryTraceStore, TraceBuilder


def _event(
    name: str,
    metadata: dict[str, object] | None = None,
    *,
    iteration: int | None = None,
    item_id: str | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        session_id="s1",
        user_id="u1",
        run_id="r1",
        sequence=1,
        kind="observation",
        source="runtime",
        name=name,
        iteration=iteration,
        item_id=item_id,
        metadata=metadata or {},
    )


def test_builds_trace_from_runtime_events() -> None:
    store = InMemoryTraceStore()
    builder = TraceBuilder(store)
    events = [
        _event(
            "runtime.started",
            {"started_at": "2026-01-01T00:00:00Z", "agent_role": "primary"},
        ),
        _event("user.message", {"content": "hello"}),
        _event(
            "runtime.context_ready",
            {"system_prompt": "system", "injected_skill_names": ["search"]},
        ),
        _event(
            "model.response",
            {
                "content": "calling",
                "provider": "openai-compatible",
                "model": "model-1",
                "tool_calls": [{"id": "tc1", "name": "echo", "arguments": {}}],
                "usage": {"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.01},
                "started_at": "start",
                "completed_at": "end",
                "duration_ms": 3,
            },
            iteration=1,
        ),
        _event(
            "tool.result",
            {
                "tool_call_id": "tc1",
                "tool_name": "echo",
                "status": "success",
                "arguments": {"value": "ping"},
                "content": "pong",
                "metadata": {},
                "structured_content": {},
                "started_at": "start",
                "completed_at": "end",
                "duration_ms": 2,
            },
            iteration=1,
            item_id="tc1",
        ),
        _event(
            "runtime.completed",
            {
                "status": "success",
                "final_response": "done",
                "attempt_count": 1,
                "completed_at": "2026-01-01T00:00:01Z",
                "duration_ms": 1000,
            },
            iteration=1,
        ),
    ]

    for event in events:
        builder.handle(event)

    trace = store.traces[0]
    assert trace.trace_id == "r1"
    assert trace.user_message == "hello"
    assert trace.system_prompt == "system"
    assert trace.injected_skill_names == ["search"]
    assert trace.final_response == "done"
    assert trace.total_iterations == 1
    assert trace.model_calls[0].input_tokens == 10
    assert trace.tool_executions[0].arguments == {"value": "ping"}
    assert trace.tool_names == ["echo"]
