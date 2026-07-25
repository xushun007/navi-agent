from __future__ import annotations

from typing import Protocol

from .models import MemoryAuditRecord, MemoryRecall, MemoryRecord, MemoryWriteProvenance


class MemoryStore(Protocol):
    def list_for_user(self, user_id: str) -> list[MemoryRecord]: ...
    def search_for_user(self, user_id: str, query: str, limit: int) -> list[MemoryRecord]: ...
    def recall_for_user(
        self,
        user_id: str,
        query: str,
        *,
        profile_limit: int,
        relevant_limit: int,
    ) -> MemoryRecall: ...
    def add_for_user(
        self,
        user_id: str,
        content: str,
        kind: str = "fact",
        target: str = "",
        source: str = "unknown",
        source_session_id: str = "",
        *,
        provenance: MemoryWriteProvenance | None = None,
        conflict_resolution: str = "",
        evidence: str = "",
    ) -> MemoryRecord: ...
    def get_for_user(self, user_id: str, record_id: str) -> MemoryRecord | None: ...
    def update_for_user(
        self,
        user_id: str,
        record_id: str,
        content: str,
        *,
        provenance: MemoryWriteProvenance | None = None,
        conflict_resolution: str = "",
        evidence: str = "",
    ) -> MemoryRecord | None: ...
    def remove_for_user(
        self,
        user_id: str,
        record_id: str,
        *,
        provenance: MemoryWriteProvenance | None = None,
    ) -> bool: ...
    def audit_for_user(self, user_id: str) -> list[MemoryAuditRecord]: ...
