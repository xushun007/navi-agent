from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryWriteProvenance:
    source: str = "unknown"
    source_session_id: str = ""
    source_trace_id: str = ""
    review_run_id: str = ""


@dataclass(slots=True)
class MemoryRecord:
    id: str
    user_id: str
    kind: str
    content: str
    target: str = "memory"
    source: str = "unknown"
    source_session_id: str = ""


@dataclass(frozen=True, slots=True)
class MemoryAuditRecord:
    id: str
    memory_id: str
    user_id: str
    action: str
    timestamp: str
    source: str = "unknown"
    source_session_id: str = ""
    source_trace_id: str = ""
    review_run_id: str = ""
    before_content: str = ""
    after_content: str = ""


@dataclass(frozen=True, slots=True)
class MemoryRecall:
    profile: list[MemoryRecord]
    relevant: list[MemoryRecord]
