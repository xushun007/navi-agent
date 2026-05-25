from __future__ import annotations

from typing import Protocol

from .models import MemoryRecord


class MemoryStore(Protocol):
    def list_for_user(self, user_id: str) -> list[MemoryRecord]: ...
