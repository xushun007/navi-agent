from __future__ import annotations

from typing import Protocol

from .models import ConversationState, Message


class SessionStore(Protocol):
    def load(self, session_id: str, user_id: str) -> ConversationState: ...

    def append(self, session: ConversationState, message: Message) -> None: ...

    def snapshot(self, session: ConversationState) -> list[Message]: ...
