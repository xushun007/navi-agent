from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile

import pytest

from navi_agent.runtime import (
    AgentRuntime,
    InMemorySessionStore,
    Message,
    ModelRequest,
    ModelResponse,
    SessionMetadata,
    SQLiteSessionStore,
    StepSnapshot,
    ToolCall,
    ToolContext,
    ToolRegistry,
    ToolResult,
)
from navi_agent.runtime.steps import context_projection_hash, tool_schema_projection_hash
from navi_agent.telemetry import InMemoryRuntimeEventStore


class _RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=[ToolCall(id="tc1", name="inspect", arguments={})]
            )
        return ModelResponse(content="done")


def test_runtime_binds_one_immutable_snapshot_to_each_step() -> None:
    transport = _RecordingTransport()
    contexts: list[ToolContext] = []
    session_store = InMemorySessionStore()
    event_store = InMemoryRuntimeEventStore()

    def inspect(context: ToolContext) -> ToolResult:
        contexts.append(context)
        return ToolResult.ok(name="inspect", content="ok")

    runtime = AgentRuntime(
        transport=transport,
        session_store=session_store,
        event_store=event_store,
        tool_registry=ToolRegistry(tools={"inspect": inspect}),
        model="model-1",
    )

    result = runtime.run_conversation("session-1", "user-1", "inspect this")

    first_request, second_request = transport.requests
    assert first_request.step_id
    assert second_request.step_id
    assert first_request.step_id != second_request.step_id
    assert contexts[0].step_id == first_request.step_id

    first_snapshot = session_store.get_step_snapshot(first_request.step_id)
    assert first_snapshot is not None
    assert first_snapshot.run_id == result.run_id
    assert first_snapshot.iteration == 1
    assert first_snapshot.model == "model-1"
    assert first_snapshot.capability_names == ("inspect",)
    assert first_snapshot.prompt_sources
    assert first_snapshot.context_hash == context_projection_hash(first_request.messages)
    assert first_snapshot.tool_schema_hash == tool_schema_projection_hash(first_request.tools)
    with pytest.raises(FrozenInstanceError):
        first_snapshot.context_hash = "changed"  # type: ignore[misc]

    first_step_events = [
        event
        for event in event_store.list_events(run_id=result.run_id)
        if event.iteration == 1
    ]
    assert first_step_events
    assert {event.step_id for event in first_step_events} == {first_request.step_id}
    snapshot_event = next(event for event in first_step_events if event.name == "step.snapshot")
    assert snapshot_event.item_id == first_request.step_id
    assert snapshot_event.metadata["context_hash"] == first_snapshot.context_hash


def test_sqlite_step_snapshot_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteSessionStore(Path(tmpdir) / "state.db")
        session = store.load("session-1", "user-1")
        store.start_run(session, "run-1", SessionMetadata(environment_id="env-1"))
        snapshot = StepSnapshot(
            step_id="step-1",
            run_id="run-1",
            session_id="session-1",
            iteration=2,
            model="model-1",
            environment_id="env-1",
            context_hash="context-hash",
            tool_schema_hash="tool-hash",
            capability_names=("read", "write"),
            prompt_sources=("base", "project_context"),
            created_at="2026-09-21T00:00:00.000+00:00",
        )

        store.save_step_snapshot(snapshot)

        assert store.get_step_snapshot("step-1") == snapshot
        assert store.get_step_snapshot("missing") is None


def test_projection_hashes_are_stable_for_equivalent_inputs() -> None:
    messages = [Message(role="user", content="hello")]
    first_tools = [{"name": "read", "parameters": {"type": "object"}}]
    second_tools = [{"parameters": {"type": "object"}, "name": "read"}]

    assert context_projection_hash(messages) == context_projection_hash(list(messages))
    assert tool_schema_projection_hash(first_tools) == tool_schema_projection_hash(second_tools)
