from __future__ import annotations

from ..models import ConversationState, Message, SessionMetadata


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationState] = {}

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
