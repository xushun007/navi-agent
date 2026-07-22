from navi_agent.events import RuntimeEvent
from navi_agent.ui_events import UiEvent, UiEventEmitter, UiEventMapper


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


def test_ignores_model_content_and_reasoning() -> None:
    ui_event = UiEventMapper().map(
        _event(
            "model.response",
            {"content": "answer", "reasoning_content": "private reasoning"},
        )
    )

    assert ui_event is None


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
