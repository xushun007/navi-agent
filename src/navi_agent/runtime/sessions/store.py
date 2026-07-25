from __future__ import annotations

from typing import Protocol

from ..models import ContextCompactionCheckpoint, ConversationState, Message, SessionMetadata


class SessionStore(Protocol):
    def load(
        self,
        session_id: str,
        user_id: str,
        metadata: SessionMetadata | None = None,
    ) -> ConversationState: ...

    def append(self, session: ConversationState, message: Message) -> None: ...

    def snapshot(self, session: ConversationState) -> list[Message]: ...

    def load_compaction_checkpoint(
        self,
        session: ConversationState,
    ) -> ContextCompactionCheckpoint | None: ...

    def save_compaction_checkpoint(
        self,
        session: ConversationState,
        checkpoint: ContextCompactionCheckpoint,
    ) -> None: ...
