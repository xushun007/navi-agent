from __future__ import annotations

import uuid
from datetime import UTC, datetime

from .models import MemoryAuditRecord, MemoryRecall, MemoryRecord, MemoryWriteProvenance
from .search import recall_memories, search_memories
from .validation import normalize_memory_content, validate_memory_content


class InMemoryMemoryStore:
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records = records or []
        self._audit_records: list[MemoryAuditRecord] = []

    def list_for_user(self, user_id: str) -> list[MemoryRecord]:
        return [record for record in self._records if record.user_id == user_id]

    def search_for_user(self, user_id: str, query: str, limit: int) -> list[MemoryRecord]:
        return search_memories(self.list_for_user(user_id), query=query, limit=limit)

    def recall_for_user(
        self,
        user_id: str,
        query: str,
        *,
        profile_limit: int,
        relevant_limit: int,
    ) -> MemoryRecall:
        return recall_memories(
            self.list_for_user(user_id),
            query=query,
            profile_limit=profile_limit,
            relevant_limit=relevant_limit,
        )

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
    ) -> MemoryRecord:
        provenance = provenance or MemoryWriteProvenance(
            source=source,
            source_session_id=source_session_id,
        )
        content = normalize_memory_content(content)
        validation_error = validate_memory_content(content)
        if validation_error:
            raise ValueError(validation_error)
        target = target or ("user" if kind == "preference" else "memory")
        for record in self._records:
            if (
                record.user_id == user_id
                and record.kind == kind
                and record.target == target
                and normalize_memory_content(record.content) == content
            ):
                self._record_audit(
                    record,
                    action="conflict_resolved",
                    provenance=provenance,
                    before_content=record.content,
                    after_content=record.content,
                )
                return record
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            kind=kind,
            content=content,
            target=target,
            source=provenance.source,
            source_session_id=provenance.source_session_id,
        )
        self._records.append(record)
        self._record_audit(
            record,
            action="add",
            provenance=provenance,
            after_content=record.content,
        )
        return record

    def get_for_user(self, user_id: str, record_id: str) -> MemoryRecord | None:
        for record in self._records:
            if record.user_id == user_id and record.id == record_id:
                return record
        return None

    def update_for_user(
        self,
        user_id: str,
        record_id: str,
        content: str,
        *,
        provenance: MemoryWriteProvenance | None = None,
    ) -> MemoryRecord | None:
        record = self.get_for_user(user_id, record_id)
        if record is None:
            return None
        validation_error = validate_memory_content(content)
        if validation_error:
            raise ValueError(validation_error)
        before_content = record.content
        record.content = normalize_memory_content(content)
        self._record_audit(
            record,
            action="update",
            provenance=provenance or MemoryWriteProvenance(),
            before_content=before_content,
            after_content=record.content,
        )
        return record

    def remove_for_user(
        self,
        user_id: str,
        record_id: str,
        *,
        provenance: MemoryWriteProvenance | None = None,
    ) -> bool:
        for index, record in enumerate(self._records):
            if record.user_id == user_id and record.id == record_id:
                self._records.pop(index)
                self._record_audit(
                    record,
                    action="remove",
                    provenance=provenance or MemoryWriteProvenance(),
                    before_content=record.content,
                )
                return True
        return False

    def audit_for_user(self, user_id: str) -> list[MemoryAuditRecord]:
        return [record for record in self._audit_records if record.user_id == user_id]

    def _record_audit(
        self,
        record: MemoryRecord,
        *,
        action: str,
        provenance: MemoryWriteProvenance,
        before_content: str = "",
        after_content: str = "",
    ) -> None:
        self._audit_records.append(
            MemoryAuditRecord(
                id=uuid.uuid4().hex[:12],
                memory_id=record.id,
                user_id=record.user_id,
                action=action,
                timestamp=datetime.now(UTC).isoformat(),
                source=provenance.source,
                source_session_id=provenance.source_session_id,
                source_trace_id=provenance.source_trace_id,
                review_run_id=provenance.review_run_id,
                before_content=before_content,
                after_content=after_content,
            )
        )
