from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryRecord:
    user_id: str
    content: str
