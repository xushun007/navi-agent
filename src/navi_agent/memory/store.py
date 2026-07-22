from __future__ import annotations

from typing import Protocol

from .models import MemoryRecord


class MemoryStore(Protocol):
    def list_for_user(self, user_id: str) -> list[MemoryRecord]: ...
    def search_for_user(self, user_id: str, query: str, limit: int) -> list[MemoryRecord]: ...
    def add_for_user(
        self,
        user_id: str,
        content: str,
        kind: str = "fact",
        target: str = "",
        source: str = "unknown",
        source_session_id: str = "",
    ) -> MemoryRecord: ...
    def get_for_user(self, user_id: str, record_id: str) -> MemoryRecord | None: ...
    def update_for_user(self, user_id: str, record_id: str, content: str) -> MemoryRecord | None: ...
    def remove_for_user(self, user_id: str, record_id: str) -> bool: ...
