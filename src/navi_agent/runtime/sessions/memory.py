from __future__ import annotations

from navi_agent.tooling import ToolResult

from ..models import (
    ContextCompactionCheckpoint,
    ConversationState,
    Message,
    ModelResponse,
    RuntimeRunRecord,
    SessionMetadata,
    ToolCall,
)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationState] = {}
        self._compaction_checkpoints: dict[str, ContextCompactionCheckpoint] = {}
        self._runs: dict[str, RuntimeRunRecord] = {}
        self._tool_results: dict[tuple[str, str], ToolResult] = {}

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
        return session

    def append(self, session: ConversationState, message: Message) -> None:
        session.messages.append(message)

    def snapshot(self, session: ConversationState) -> list[Message]:
        return list(session.messages)

    def start_run(
        self,
        session: ConversationState,
        run_id: str,
        metadata: SessionMetadata,
    ) -> None:
        import time

        now = time.time()
        self._runs[run_id] = RuntimeRunRecord(
            run_id=run_id,
            session_id=session.session_id,
            user_id=session.user_id,
            source=metadata.source,
            agent_role=metadata.agent_role,
            status="running",
            started_at=now,
            updated_at=now,
            start_message_id=len(session.messages) + 1,
            model=metadata.model,
        )

    def get_run(self, run_id: str) -> RuntimeRunRecord | None:
        return self._runs.get(run_id)

    def start_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        tool_call: ToolCall,
    ) -> None:
        return None

    def get_tool_result(self, run_id: str, tool_call_id: str) -> ToolResult | None:
        return self._tool_results.get((run_id, tool_call_id))

    def complete_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        result: ToolResult,
    ) -> None:
        if result.structured_content.get("interaction_pending") is True:
            return
        self._tool_results[(run_id, result.tool_call_id)] = result

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
