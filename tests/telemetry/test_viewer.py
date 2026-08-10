from pathlib import Path

from navi_agent.events import RuntimeEvent
from navi_agent.telemetry import (
    InMemoryRuntimeEventStore,
    InMemoryTraceStore,
    ModelCallTrace,
    RuntimeTrace,
    ToolExecutionTrace,
)
from navi_agent.telemetry.viewer import (
    TraceViewerService,
    render_session_html,
    render_session_index_html,
    render_trace_html,
)


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
        model_calls=[
            ModelCallTrace(
                iteration=1,
                response_content="",
                input_tokens=1_200,
                output_tokens=300,
                cache_read_tokens=800,
                cache_write_tokens=40,
                reasoning_tokens=50,
                cost_usd=0.012345,
            )
        ],
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
                metadata=(
                    {
                        "usage": {
                            "input_tokens": 1_200,
                            "output_tokens": 300,
                            "cache_read_tokens": 800,
                            "cache_write_tokens": 40,
                            "reasoning_tokens": 50,
                            "cost_usd": 0.012345,
                        }
                    }
                    if name == "model.response"
                    else {"tool_name": "skill_view"}
                ),
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
    assert "<strong>1,200</strong>input" in html
    assert "<strong>300</strong>output" in html
    assert "<strong>$0.012345</strong>cost" in html
    assert (
        "input 1,200 / output 300 / cache read 800 / cache write 40 / reasoning 50"
        in html
    )

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


def test_trace_viewer_lists_sessions_and_links_traces() -> None:
    trace_store = InMemoryTraceStore()
    trace_store.record(
        RuntimeTrace(
            trace_id="trace-1",
            session_id="session/one",
            user_id="user-1",
            user_message="Write update",
            final_response="Done",
            status="success",
            model_calls=[
                ModelCallTrace(
                    iteration=1,
                    response_content="Done",
                    input_tokens=900,
                    output_tokens=100,
                    cost_usd=0.02,
                ),
                ModelCallTrace(
                    iteration=2,
                    response_content="Done",
                    input_tokens=1_100,
                    output_tokens=200,
                    cost_usd=0.03,
                ),
            ],
            tool_executions=[
                ToolExecutionTrace(
                    iteration=1,
                    tool_call_id="call-1",
                    tool_name="skill_view",
                    status="success",
                    arguments={"skill_name": "internal-comms"},
                )
            ],
        )
    )
    service = TraceViewerService(
        trace_store=trace_store,
        event_store=InMemoryRuntimeEventStore(),
    )

    sessions = service.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].loaded_skill_names == ("internal-comms",)

    index_html = render_session_index_html(sessions)
    session_html = render_session_html(sessions[0])
    assert '/session/session%2Fone' in index_html
    assert '/trace/trace-1' in session_html
    assert "internal-comms" in index_html
    assert "<strong>2,000</strong>input" in session_html
    assert "<strong>300</strong>output" in session_html
    assert "<strong>$0.050000</strong>cost" in session_html
    assert "2,000 input · 300 output" in index_html
    assert "input:<br>" not in index_html


def test_trace_viewer_does_not_report_partial_cost_as_total() -> None:
    trace = RuntimeTrace(
        trace_id="trace-cost",
        session_id="session-cost",
        user_id="user-1",
        user_message="Hello",
        final_response="Hi",
        status="success",
        model_calls=[
            ModelCallTrace(
                iteration=1,
                response_content="",
                input_tokens=10,
                output_tokens=2,
                cost_usd=0.01,
            ),
            ModelCallTrace(
                iteration=2,
                response_content="Hi",
                input_tokens=20,
                output_tokens=4,
            ),
        ],
    )
    trace_store = InMemoryTraceStore()
    trace_store.record(trace)
    record = TraceViewerService(
        trace_store=trace_store,
        event_store=InMemoryRuntimeEventStore(),
    ).get_trace("trace-cost")

    assert record is not None
    html = render_trace_html(record)
    assert "<strong>30</strong>input" in html
    assert "<strong>6</strong>output" in html
    assert "<strong>—</strong>cost" in html
    assert "$0.010000" not in html
