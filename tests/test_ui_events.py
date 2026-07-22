from navi_agent.events import RuntimeEvent
from navi_agent.ui_events import ConsoleUiEventSink, UiEvent, UiEventEmitter, UiEventMapper


def _event(name: str, metadata: dict[str, object], *, item_id: str | None = None) -> RuntimeEvent:
    return RuntimeEvent(
        session_id="s1",
        user_id="u1",
        run_id="r1",
        sequence=3,
        kind="observation",
        source="runtime",
        name=name,
        item_id=item_id,
        metadata=metadata,
    )


def test_maps_tool_lifecycle_with_stable_item_identity() -> None:
    mapper = UiEventMapper()
    started = mapper.map(
        _event(
            "tool.call",
            {"tool_name": "read_file", "arguments": {"path": "/workspace/README.md"}},
            item_id="tc1",
        )
    )
    completed = mapper.map(
        _event(
            "tool.result",
            {"tool_name": "read_file", "status": "success"},
            item_id="tc1",
        )
    )

    assert started is not None
    assert completed is not None
    assert started.item_id == completed.item_id == "tc1"
    assert started.state == "started"
    assert started.title == "正在读取 README.md"
    assert completed.state == "completed"
    assert completed.title == "已读取文件"


def test_redacts_and_truncates_tool_failure_detail() -> None:
    ui_event = UiEventMapper().map(
        _event(
            "tool.result",
            {
                "tool_name": "bash",
                "status": "error",
                "content": "token=super-secret " + ("failure " * 40),
            },
            item_id="tc1",
        )
    )

    assert ui_event is not None
    assert ui_event.state == "failed"
    assert ui_event.severity == "error"
    assert "super-secret" not in (ui_event.detail or "")
    assert "token=<redacted>" in (ui_event.detail or "")
    assert len(ui_event.detail or "") <= 160


def test_model_response_only_marks_stream_completion() -> None:
    ui_event = UiEventMapper().map(
        _event(
            "model.response",
            {"content": "answer", "reasoning_content": "private reasoning"},
            item_id="model:1",
        )
    )

    assert ui_event is not None
    assert ui_event.kind == "assistant"
    assert ui_event.state == "completed"
    assert ui_event.item_id == "model:1"
    assert ui_event.detail is None
    assert "answer" not in repr(ui_event)
    assert "private" not in repr(ui_event)


def test_maps_only_public_model_text_delta() -> None:
    ui_event = UiEventMapper().map(
        _event(
            "model.delta",
            {"delta": "hello", "reasoning_content": "private reasoning"},
            item_id="model:1",
        )
    )

    assert ui_event is not None
    assert ui_event.kind == "assistant"
    assert ui_event.state == "delta"
    assert ui_event.detail == "hello"
    assert ui_event.item_id == "model:1"
    assert "private" not in repr(ui_event)


def test_maps_runtime_cancellation_without_treating_it_as_failure() -> None:
    mapper = UiEventMapper()

    cancelled = mapper.map(_event("runtime.cancelled", {"reason": "user_stop"}))
    completed = mapper.map(_event("runtime.completed", {"status": "cancelled"}))

    assert cancelled is not None
    assert cancelled.kind == "runtime"
    assert cancelled.state == "cancelled"
    assert cancelled.severity == "info"
    assert completed is None


def test_maps_runtime_waiting_without_treating_it_as_failure() -> None:
    mapper = UiEventMapper()

    waiting = mapper.map(_event("runtime.waiting", {"interaction_kind": "clarification"}))
    completed = mapper.map(_event("runtime.completed", {"status": "awaiting_input"}))

    assert waiting is not None
    assert waiting.state == "waiting"
    assert waiting.severity == "info"
    assert completed is None


def test_maps_tool_progress_without_exposing_secrets() -> None:
    ui_event = UiEventMapper().map(
        _event(
            "tool.progress",
            {
                "tool_name": "bash",
                "stream": "stdout",
                "chunk": "token=super-secret tests are still running",
            },
            item_id="tc1",
        )
    )

    assert ui_event is not None
    assert ui_event.state == "progress"
    assert ui_event.title == "命令仍在执行"
    assert ui_event.detail == "token=<redacted> tests are still running"


def test_emitter_only_sends_derived_ui_events() -> None:
    received: list[UiEvent] = []

    class Sink:
        def handle(self, event: UiEvent) -> None:
            received.append(event)

    emitter = UiEventEmitter(Sink())
    emitter.handle(_event("iteration.started", {}))
    emitter.handle(
        _event(
            "tool.call",
            {"tool_name": "search_files", "arguments": {"pattern": "RuntimeEvent"}},
            item_id="tc1",
        )
    )

    assert [event.title for event in received] == ["正在搜索文件"]


def test_console_sink_renders_safe_ui_events_once() -> None:
    from io import StringIO

    output = StringIO()
    sink = ConsoleUiEventSink(output)
    event = UiEvent(
        event_id="event-1",
        run_id="run-1",
        sequence=1,
        kind="tool",
        state="failed",
        title="命令执行失败",
        detail="exit code 1",
        severity="error",
    )

    sink.handle(event)
    sink.handle(event)

    assert output.getvalue() == "✗ 命令执行失败 — exit code 1\n"


def test_console_sink_replaces_live_status_and_commits_completion() -> None:
    from io import StringIO

    class TerminalBuffer(StringIO):
        def isatty(self) -> bool:
            return True

    output = TerminalBuffer()
    sink = ConsoleUiEventSink(output)
    sink.handle(
        UiEvent(
            event_id="event-1",
            run_id="run-1",
            sequence=1,
            kind="tool",
            state="started",
            title="正在读取 README.md",
            item_id="tool-1",
            replaceable=True,
        )
    )
    sink.handle(
        UiEvent(
            event_id="event-2",
            run_id="run-1",
            sequence=2,
            kind="tool",
            state="completed",
            title="已读取文件",
            item_id="tool-1",
            replaceable=True,
        )
    )

    assert output.getvalue() == (
        "\r\x1b[2K› 正在读取 README.md"
        "\r\x1b[2K"
        "✓ 已读取文件\n"
    )


def test_console_sink_streams_assistant_content_and_tracks_final_response() -> None:
    from io import StringIO

    output = StringIO()
    sink = ConsoleUiEventSink(output)
    for sequence, delta in enumerate(["hello ", "world"], start=1):
        sink.handle(
            UiEvent(
                event_id=f"event-{sequence}",
                run_id="run-1",
                sequence=sequence,
                kind="assistant",
                state="delta",
                title="",
                item_id="model:1",
                detail=delta,
            )
        )
    sink.handle(
        UiEvent(
            event_id="event-3",
            run_id="run-1",
            sequence=3,
            kind="assistant",
            state="completed",
            title="",
            item_id="model:1",
        )
    )

    sink.finish()

    assert output.getvalue() == "hello world\n"
    assert sink.rendered_response("hello world")
    assert not sink.rendered_response("different response")
