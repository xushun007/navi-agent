from __future__ import annotations

from .models import MemoryRecord


class InMemoryMemoryStore:
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records = records or []

    def list_for_user(self, user_id: str) -> list[MemoryRecord]:
        return [record for record in self._records if record.user_id == user_id]
