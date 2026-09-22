from __future__ import annotations

import sqlite3
from pathlib import Path
import tempfile

import pytest

from navi_agent.runtime import (
    AgentRuntime,
    InMemorySessionStore,
    ModelRequest,
    ModelResponse,
    OperationStatus,
    SessionMetadata,
    SQLiteSessionStore,
    ToolCall,
    ToolContext,
    ToolRegistry,
    ToolResult,
)
from navi_agent.runtime.operations import operation_result_hash
from navi_agent.telemetry import InMemoryRuntimeEventStore


class _RepeatingTransport:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) <= 2:
            return ModelResponse(
                tool_calls=[ToolCall(id="tc1", name="write", arguments={"value": "x"})]
            )
        return ModelResponse(content="done")


def test_runtime_correlates_and_deduplicates_tool_operation() -> None:
    transport = _RepeatingTransport()
    session_store = InMemorySessionStore()
    event_store = InMemoryRuntimeEventStore()
    contexts: list[ToolContext] = []

    def write(value: str, context: ToolContext) -> ToolResult:
        contexts.append(context)
        return ToolResult.ok(name="write", content=value)

    runtime = AgentRuntime(
        transport=transport,
        session_store=session_store,
        event_store=event_store,
        tool_registry=ToolRegistry(tools={"write": write}),
        max_iterations=3,
    )

    result = runtime.run_conversation("session-1", "user-1", "write once")

    assert result.status == "success"
    assert len(contexts) == 1
    operation = session_store.get_operation_for_tool_call(result.run_id, "tc1")
    assert operation is not None
    assert operation.status is OperationStatus.SUCCEEDED
    assert operation.step_id == transport.requests[0].step_id
    assert operation.environment_id
    assert contexts[0].operation_id == operation.operation_id
    tool_events = [
        event
        for event in event_store.list_events(run_id=result.run_id)
        if event.name in {"tool.call", "tool.result"}
    ]
    assert len(tool_events) == 4
    assert {event.operation_id for event in tool_events} == {operation.operation_id}
    assert result.tool_results[-1].metadata["deduplicated"] is True


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_operation_lifecycle_and_idempotent_planning(store_kind: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "state.db"
        store = (
            InMemorySessionStore()
            if store_kind == "memory"
            else SQLiteSessionStore(db_path)
        )
        session = store.load("session-1", "user-1")
        store.start_run(
            session,
            "run-1",
            SessionMetadata(environment_id="environment-1"),
        )
        call = ToolCall(id="tc1", name="write", arguments={"path": "a.txt"})

        planned = store.plan_operation(
            session,
            "run-1",
            call,
            step_id="step-1",
            environment_id="environment-1",
        )

        assert planned.status is OperationStatus.PLANNED
        assert store.list_incomplete_operations("run-1") == [planned]
        assert (
            store.plan_operation(
                session,
                "run-1",
                call,
                step_id="step-1",
                environment_id="environment-1",
            ).operation_id
            == planned.operation_id
        )
        with pytest.raises(ValueError, match="different input"):
            store.plan_operation(
                session,
                "run-1",
                ToolCall(id="tc1", name="write", arguments={"path": "b.txt"}),
                step_id="step-1",
                environment_id="environment-1",
            )
        with pytest.raises(ValueError, match="invalid operation status transition"):
            store.complete_operation(
                planned.operation_id,
                ToolResult.ok(name="write", content="written").bind("tc1"),
            )

        running = store.mark_operation_running(planned.operation_id)
        waiting = store.complete_operation(
            running.operation_id,
            ToolResult.ok(
                name="write",
                content="approve?",
                structured_content={"interaction_pending": True},
            ).bind("tc1"),
        )

        assert waiting.status is OperationStatus.AWAITING_INPUT
        assert waiting.completed_at is None
        assert store.get_tool_result("run-1", "tc1") is None
        resumed = store.mark_operation_running(waiting.operation_id)
        succeeded = store.complete_operation(
            resumed.operation_id,
            ToolResult.ok(name="write", content="written").bind("tc1"),
        )
        assert succeeded.status is OperationStatus.SUCCEEDED
        assert succeeded.result_hash
        assert succeeded.completed_at is not None
        if store_kind == "sqlite":
            assert SQLiteSessionStore(db_path).get_operation(succeeded.operation_id) == succeeded
        assert store.list_incomplete_operations("run-1") == []
        assert store.get_tool_result("run-1", "tc1") is not None
        with pytest.raises(ValueError, match="invalid operation status transition"):
            store.mark_operation_running(succeeded.operation_id)

        failed_call = ToolCall(id="tc2", name="write", arguments={})
        failed_operation = store.plan_operation(
            session,
            "run-1",
            failed_call,
            step_id="step-2",
            environment_id="environment-1",
        )
        store.mark_operation_running(failed_operation.operation_id)
        failed = store.complete_operation(
            failed_operation.operation_id,
            ToolResult.error(name="write", content="denied").bind("tc2"),
        )
        assert failed.status is OperationStatus.FAILED


def test_result_hash_ignores_runtime_trace_timing() -> None:
    first = ToolResult.ok(
        name="write",
        content="written",
        metadata={"source": "tool", "_trace_duration_ms": 1},
    )
    second = ToolResult.ok(
        name="write",
        content="written",
        metadata={"source": "tool", "_trace_duration_ms": 999},
    )

    assert operation_result_hash(first) == operation_result_hash(second)


def test_sqlite_migrates_legacy_tool_execution_records() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, environment_id TEXT)")
    connection.execute("INSERT INTO runs VALUES ('run-1', 'environment-1')")
    connection.execute(
        """
        CREATE TABLE tool_executions (
            run_id TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            started_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL,
            PRIMARY KEY (run_id, tool_call_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO tool_executions VALUES (
            'run-1', 'tc1', 'session-1', 'write', '{"path":"a.txt"}',
            'completed', '{"status":"success"}', 1.0, 2.0, 2.0
        )
        """
    )

    SQLiteSessionStore._migrate_operation_columns(connection)

    row = connection.execute("SELECT * FROM tool_executions").fetchone()
    assert row["operation_id"].startswith("legacy:")
    assert row["step_id"] == ""
    assert row["environment_id"] == "environment-1"
    assert row["arguments_hash"]
    assert row["status"] == "succeeded"
    connection.close()
