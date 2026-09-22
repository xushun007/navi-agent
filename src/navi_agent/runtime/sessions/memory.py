from __future__ import annotations

import time
from dataclasses import replace
from uuid import uuid4

from navi_agent.tooling import ToolResult

from ..models import (
    ContextCompactionCheckpoint,
    ConversationState,
    Message,
    ModelResponse,
    OperationRecord,
    OperationStatus,
    RuntimeRunRecord,
    SessionMetadata,
    SessionSummary,
    StepSnapshot,
    ToolCall,
)
from ..operations import (
    operation_arguments_hash,
    operation_result_hash,
    operation_status_for_result,
    validate_operation_transition,
)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationState] = {}
        self._compaction_checkpoints: dict[str, ContextCompactionCheckpoint] = {}
        self._runs: dict[str, RuntimeRunRecord] = {}
        self._tool_results: dict[tuple[str, str], ToolResult] = {}
        self._step_snapshots: dict[str, StepSnapshot] = {}
        self._operations: dict[str, OperationRecord] = {}
        self._operation_ids_by_tool_call: dict[tuple[str, str], str] = {}
        self._updated_at: dict[str, float] = {}

    def load(
        self,
        session_id: str,
        user_id: str,
        metadata: SessionMetadata | None = None,
    ) -> ConversationState:
        session = self._sessions.get(session_id)
        if session is None:
            session = ConversationState(session_id=session_id, user_id=user_id)
            self._sessions[session_id] = session
            self._updated_at[session_id] = time.time()
        return session

    def append(self, session: ConversationState, message: Message) -> None:
        session.messages.append(message)
        self._updated_at[session.session_id] = time.time()

    def snapshot(self, session: ConversationState) -> list[Message]:
        return list(session.messages)

    def has_session(self, session_id: str, user_id: str) -> bool:
        session = self._sessions.get(session_id)
        return session is not None and session.user_id == user_id

    def list_sessions(self, user_id: str, limit: int = 10) -> list[SessionSummary]:
        sessions = [
            SessionSummary(
                session_id=session.session_id,
                updated_at=self._updated_at.get(session.session_id, 0),
                message_count=len(session.messages),
            )
            for session in self._sessions.values()
            if session.user_id == user_id
        ]
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)[:limit]

    def start_run(
        self,
        session: ConversationState,
        run_id: str,
        metadata: SessionMetadata,
    ) -> None:
        import time

        now = time.time()
        for existing_run in self._runs.values():
            if (
                existing_run.session_id == session.session_id
                and existing_run.status in {"started", "running"}
            ):
                existing_run.status = "interrupted"
                existing_run.updated_at = now
                existing_run.completed_at = now
                existing_run.completion_reason = "superseded_by_new_run"
        self._runs[run_id] = RuntimeRunRecord(
            run_id=run_id,
            session_id=session.session_id,
            user_id=session.user_id,
            source=metadata.source,
            agent_role=metadata.agent_role,
            status="running",
            started_at=now,
            updated_at=now,
            environment_id=metadata.environment_id,
            start_message_id=len(session.messages) + 1,
            model=metadata.model,
        )

    def get_run(self, run_id: str) -> RuntimeRunRecord | None:
        return self._runs.get(run_id)

    def save_step_snapshot(self, snapshot: StepSnapshot) -> None:
        self._step_snapshots[snapshot.step_id] = snapshot

    def get_step_snapshot(self, step_id: str) -> StepSnapshot | None:
        return self._step_snapshots.get(step_id)

    def plan_operation(
        self,
        session: ConversationState,
        run_id: str,
        tool_call: ToolCall,
        *,
        step_id: str,
        environment_id: str,
    ) -> OperationRecord:
        key = (run_id, tool_call.id)
        arguments_hash = operation_arguments_hash(tool_call.arguments)
        existing_id = self._operation_ids_by_tool_call.get(key)
        if existing_id is not None:
            existing = self._operations[existing_id]
            if (
                existing.capability_name != tool_call.name
                or existing.arguments_hash != arguments_hash
            ):
                raise ValueError("tool call identity was reused with different input")
            return existing
        now = time.time()
        record = OperationRecord(
            operation_id=uuid4().hex,
            run_id=run_id,
            session_id=session.session_id,
            step_id=step_id,
            environment_id=environment_id,
            tool_call_id=tool_call.id,
            capability_name=tool_call.name,
            arguments_hash=arguments_hash,
            status=OperationStatus.PLANNED,
            created_at=now,
            updated_at=now,
        )
        self._operations[record.operation_id] = record
        self._operation_ids_by_tool_call[key] = record.operation_id
        return record

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        return self._operations.get(operation_id)

    def get_operation_for_tool_call(
        self,
        run_id: str,
        tool_call_id: str,
    ) -> OperationRecord | None:
        operation_id = self._operation_ids_by_tool_call.get((run_id, tool_call_id))
        return self._operations.get(operation_id) if operation_id is not None else None

    def list_incomplete_operations(
        self,
        run_id: str | None = None,
    ) -> list[OperationRecord]:
        return sorted(
            (
                record
                for record in self._operations.values()
                if record.status
                in {
                    OperationStatus.PLANNED,
                    OperationStatus.RUNNING,
                    OperationStatus.AWAITING_INPUT,
                }
                and (run_id is None or record.run_id == run_id)
            ),
            key=lambda record: (record.created_at, record.operation_id),
        )

    def mark_operation_running(self, operation_id: str) -> OperationRecord:
        record = self._required_operation(operation_id)
        if record.status is OperationStatus.RUNNING:
            return record
        validate_operation_transition(record.status, OperationStatus.RUNNING)
        updated = replace(
            record,
            status=OperationStatus.RUNNING,
            updated_at=time.time(),
        )
        self._operations[operation_id] = updated
        return updated

    def complete_operation(
        self,
        operation_id: str,
        result: ToolResult,
    ) -> OperationRecord:
        record = self._required_operation(operation_id)
        target = operation_status_for_result(result)
        validate_operation_transition(record.status, target)
        now = time.time()
        updated = replace(
            record,
            status=target,
            result_hash=operation_result_hash(result),
            updated_at=now,
            completed_at=(
                None if target is OperationStatus.AWAITING_INPUT else now
            ),
        )
        self._operations[operation_id] = updated
        if target is not OperationStatus.AWAITING_INPUT:
            self._tool_results[(record.run_id, record.tool_call_id)] = result
        return updated

    def _required_operation(self, operation_id: str) -> OperationRecord:
        record = self._operations.get(operation_id)
        if record is None:
            raise KeyError(f"unknown operation: {operation_id}")
        return record

    def start_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        tool_call: ToolCall,
    ) -> None:
        run = self._runs.get(run_id)
        self.plan_operation(
            session,
            run_id,
            tool_call,
            step_id="",
            environment_id=(run.environment_id or "") if run is not None else "",
        )

    def get_tool_result(self, run_id: str, tool_call_id: str) -> ToolResult | None:
        return self._tool_results.get((run_id, tool_call_id))

    def complete_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        result: ToolResult,
    ) -> None:
        operation = self.get_operation_for_tool_call(run_id, result.tool_call_id)
        if operation is None:
            raise KeyError(f"unknown tool call: {run_id}/{result.tool_call_id}")
        if operation.status in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}:
            return
        if operation.status is not OperationStatus.RUNNING:
            operation = self.mark_operation_running(operation.operation_id)
        self.complete_operation(operation.operation_id, result)

    def load_compaction_checkpoint(
        self,
        session: ConversationState,
    ) -> ContextCompactionCheckpoint | None:
        return self._compaction_checkpoints.get(session.session_id)

    def save_compaction_checkpoint(
        self,
        session: ConversationState,
        checkpoint: ContextCompactionCheckpoint,
    ) -> None:
        self._compaction_checkpoints[session.session_id] = checkpoint

    def record_model_response(
        self,
        session: ConversationState,
        run_id: str,
        response: ModelResponse,
    ) -> None:
        import time

        run = self._runs[run_id]
        run.provider = response.provider or run.provider
        run.model = response.model or run.model
        run.input_tokens += response.usage.input_tokens
        run.output_tokens += response.usage.output_tokens
        run.cache_read_tokens += response.usage.cache_read_tokens
        run.cache_write_tokens += response.usage.cache_write_tokens
        run.reasoning_tokens += response.usage.reasoning_tokens
        if response.usage.cost_usd is not None:
            run.estimated_cost_usd = (run.estimated_cost_usd or 0) + response.usage.cost_usd
        run.updated_at = time.time()

    def finalize(
        self,
        session: ConversationState,
        run_id: str,
        *,
        status: str,
        end_reason: str | None = None,
        trajectory_complete: bool = True,
        failure_reason: str | None = None,
    ) -> None:
        import time

        run = self._runs[run_id]
        run.status = _run_status(status)
        run.completed_at = time.time()
        run.updated_at = run.completed_at
        run.end_message_id = len(session.messages)
        run.trajectory_complete = trajectory_complete
        run.failure_reason = failure_reason
        run.completion_reason = end_reason or status


def _run_status(status: str) -> str:
    return {
        "success": "completed",
        "iteration_limit_exceeded": "failed",
    }.get(status, status)
