from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryRecord:
    id: str
    user_id: str
    content: str
