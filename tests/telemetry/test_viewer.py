from pathlib import Path

from navi_agent.events import RuntimeEvent
from navi_agent.telemetry import (
    InMemoryRuntimeEventStore,
    InMemoryTraceStore,
    ModelCallTrace,
    RuntimeTrace,
    ToolExecutionTrace,
)
from navi_agent.telemetry.viewer import TraceViewerService, render_trace_html


def test_trace_viewer_renders_real_event_order_and_skill_usage(tmp_path: Path) -> None:
    trace = RuntimeTrace(
        trace_id="trace-1",
        session_id="session-1",
        user_id="user-1",
        user_message="Write an update",
        final_response="Done",
        status="success",
        system_prompt=(
            "[Skills]\n"
            "Available reusable procedures.\n"
            "  general:\n"
            "    - internal-comms: Write updates\n"
            "[Workspace]\nroot"
        ),
        model_calls=[ModelCallTrace(iteration=1, response_content="")],
        tool_executions=[
            ToolExecutionTrace(
                iteration=1,
                tool_call_id="call-1",
                tool_name="skill_view",
                status="success",
                arguments={"skill_name": "internal-comms"},
            ),
            ToolExecutionTrace(
                iteration=2,
                tool_call_id="call-2",
                tool_name="skill_view",
                status="success",
                arguments={
                    "skill_name": "internal-comms",
                    "attachment_path": "references/3p-updates.md",
                },
            ),
        ],
    )
    trace_store = InMemoryTraceStore()
    trace_store.record(trace)
    event_store = InMemoryRuntimeEventStore()
    for sequence, name, source in (
        (1, "model.response", "model"),
        (2, "tool.call", "agent"),
        (3, "tool.result", "tool"),
    ):
        event_store.record(
            RuntimeEvent(
                session_id="session-1",
                user_id="user-1",
                run_id="trace-1",
                sequence=sequence,
                kind="observation",
                source=source,
                name=name,
                metadata={"tool_name": "skill_view"},
            )
        )
    service = TraceViewerService(trace_store=trace_store, event_store=event_store)

    record = service.get_trace("trace-1")
    assert record is not None
    html = render_trace_html(record)

    assert record.available_skill_names == ("internal-comms",)
    assert record.loaded_skill_names == ("internal-comms",)
    assert record.loaded_skill_references == (
        "internal-comms/references/3p-updates.md",
    )
    assert html.index("model.response") < html.index("tool.call") < html.index("tool.result")

    output = service.write_trace("trace-1", tmp_path / "trace.html")
    assert output.exists()


def test_trace_viewer_escapes_and_redacts_recorded_content() -> None:
    trace = RuntimeTrace(
        trace_id="trace-unsafe",
        session_id="session-1",
        user_id="user-1",
        user_message='<script>alert("x")</script>',
        final_response="token=top-secret",
        status="success",
    )
    trace_store = InMemoryTraceStore()
    trace_store.record(trace)
    event_store = InMemoryRuntimeEventStore()
    event_store.record(
        RuntimeEvent(
            session_id="session-1",
            user_id="user-1",
            run_id="trace-unsafe",
            sequence=1,
            kind="observation",
            source="tool",
            name="tool.result",
            metadata={"content": '<img src=x>', "api_key": "secret-value"},
        )
    )

    record = TraceViewerService(
        trace_store=trace_store,
        event_store=event_store,
    ).get_trace("trace-unsafe")
    assert record is not None
    html = render_trace_html(record)

    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "top-secret" not in html
    assert "secret-value" not in html
    assert "&lt;redacted&gt;" in html
