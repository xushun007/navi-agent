from __future__ import annotations

from ..models import (
    ContextCompactionCheckpoint,
    ConversationState,
    Message,
    ModelResponse,
    SessionMetadata,
)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationState] = {}
        self._compaction_checkpoints: dict[str, ContextCompactionCheckpoint] = {}

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
        metadata: SessionMetadata,
    ) -> None:
        return None

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
        response: ModelResponse,
    ) -> None:
        return None

    def finalize(
        self,
        session: ConversationState,
        *,
        status: str,
        end_reason: str | None = None,
    ) -> None:
        return None
