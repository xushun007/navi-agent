from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryRecord:
    id: str
    user_id: str
    kind: str
    content: str
    target: str = "memory"
    source: str = "unknown"
    source_session_id: str = ""
