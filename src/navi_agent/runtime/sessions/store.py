from __future__ import annotations

from typing import Protocol

from navi_agent.tooling import ToolResult

from ..models import (
    ContextCompactionCheckpoint,
    ConversationState,
    Message,
    ModelResponse,
    OperationRecord,
    RuntimeRunRecord,
    SessionMetadata,
    SessionSummary,
    StepSnapshot,
    ToolCall,
)


class SessionStore(Protocol):
    """Authoritative conversation history and searchable session state."""

    def load(
        self,
        session_id: str,
        user_id: str,
        metadata: SessionMetadata | None = None,
    ) -> ConversationState: ...

    def append(self, session: ConversationState, message: Message) -> None: ...

    def snapshot(self, session: ConversationState) -> list[Message]: ...

    def has_session(self, session_id: str, user_id: str) -> bool: ...

    def list_sessions(self, user_id: str, limit: int = 10) -> list[SessionSummary]: ...

    def start_run(
        self,
        session: ConversationState,
        run_id: str,
        metadata: SessionMetadata,
    ) -> None: ...

    def get_run(self, run_id: str) -> RuntimeRunRecord | None: ...

    def save_step_snapshot(self, snapshot: StepSnapshot) -> None: ...

    def get_step_snapshot(self, step_id: str) -> StepSnapshot | None: ...

    def plan_operation(
        self,
        session: ConversationState,
        run_id: str,
        tool_call: ToolCall,
        *,
        step_id: str,
        environment_id: str,
    ) -> OperationRecord: ...

    def get_operation(self, operation_id: str) -> OperationRecord | None: ...

    def get_operation_for_tool_call(
        self,
        run_id: str,
        tool_call_id: str,
    ) -> OperationRecord | None: ...

    def list_incomplete_operations(
        self,
        run_id: str | None = None,
    ) -> list[OperationRecord]: ...

    def mark_operation_running(self, operation_id: str) -> OperationRecord: ...

    def complete_operation(
        self,
        operation_id: str,
        result: ToolResult,
    ) -> OperationRecord: ...

    def start_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        tool_call: ToolCall,
    ) -> None: ...

    def get_tool_result(self, run_id: str, tool_call_id: str) -> ToolResult | None: ...

    def complete_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        result: ToolResult,
    ) -> None: ...

    def load_compaction_checkpoint(
        self,
        session: ConversationState,
    ) -> ContextCompactionCheckpoint | None: ...

    def save_compaction_checkpoint(
        self,
        session: ConversationState,
        checkpoint: ContextCompactionCheckpoint,
    ) -> None: ...

    def record_model_response(
        self,
        session: ConversationState,
        run_id: str,
        response: ModelResponse,
    ) -> None: ...

    def finalize(
        self,
        session: ConversationState,
        run_id: str,
        *,
        status: str,
        end_reason: str | None = None,
        trajectory_complete: bool = True,
        failure_reason: str | None = None,
    ) -> None: ...
