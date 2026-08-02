from __future__ import annotations

import uuid
from datetime import UTC, datetime

from .conflicts import find_memory_conflicts, require_explicit_conflict_resolution
from .lifecycle import is_memory_expired, normalize_expiry
from .models import MemoryAuditRecord, MemoryRecall, MemoryRecord, MemoryWriteProvenance
from .search import recall_memories, search_memories
from .validation import normalize_memory_content, normalize_memory_target, validate_memory_content


class InMemoryMemoryStore:
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records = records or []
        self._audit_records: list[MemoryAuditRecord] = []

    def list_for_user(self, user_id: str) -> list[MemoryRecord]:
        return [
            record
            for record in self._records
            if record.user_id == user_id and not is_memory_expired(record)
        ]

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
        expires_at: str = "",
        *,
        provenance: MemoryWriteProvenance | None = None,
        conflict_resolution: str = "",
        evidence: str = "",
    ) -> MemoryRecord:
        provenance = provenance or MemoryWriteProvenance(
            source=source,
            source_session_id=source_session_id,
        )
        content = normalize_memory_content(content)
        validation_error = validate_memory_content(content)
        if validation_error:
            raise ValueError(validation_error)
        target = normalize_memory_target(target, kind=kind)
        expires_at = normalize_expiry(expires_at)
        for record in self.list_for_user(user_id):
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
        conflicts = find_memory_conflicts(
            self.list_for_user(user_id),
            content=content,
            kind=kind,
            target=target,
        )
        retained_conflicts = require_explicit_conflict_resolution(
            conflicts,
            resolution=conflict_resolution,
            evidence=evidence,
        )
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            kind=kind,
            content=content,
            target=target,
            source=provenance.source,
            source_session_id=provenance.source_session_id,
            expires_at=expires_at,
        )
        self._records.append(record)
        self._record_audit(
            record,
            action="add",
            provenance=provenance,
            after_content=record.content,
        )
        if retained_conflicts:
            self._record_audit(
                record,
                action="conflict_resolved",
                provenance=provenance,
                before_content="\n".join(item.content for item in conflicts),
                after_content=record.content,
                resolution="retain_both",
                evidence=evidence,
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
        conflict_resolution: str = "",
        evidence: str = "",
    ) -> MemoryRecord | None:
        record = self.get_for_user(user_id, record_id)
        if record is None:
            return None
        validation_error = validate_memory_content(content)
        if validation_error:
            raise ValueError(validation_error)
        normalized_content = normalize_memory_content(content)
        conflicts = find_memory_conflicts(
            self.list_for_user(user_id),
            content=normalized_content,
            kind=record.kind,
            target=record.target,
            exclude_record_id=record_id,
        )
        retained_conflicts = require_explicit_conflict_resolution(
            conflicts,
            resolution=conflict_resolution,
            evidence=evidence,
        )
        before_content = record.content
        record.content = normalized_content
        self._record_audit(
            record,
            action="update",
            provenance=provenance or MemoryWriteProvenance(),
            before_content=before_content,
            after_content=record.content,
        )
        if retained_conflicts:
            self._record_audit(
                record,
                action="conflict_resolved",
                provenance=provenance or MemoryWriteProvenance(),
                before_content="\n".join(item.content for item in conflicts),
                after_content=record.content,
                resolution="retain_both",
                evidence=evidence,
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

    def expire_for_user(self, user_id: str, *, now: datetime | None = None) -> int:
        expired = [
            record
            for record in self._records
            if record.user_id == user_id and is_memory_expired(record, now=now)
        ]
        if not expired:
            return 0
        expired_ids = {record.id for record in expired}
        self._records = [record for record in self._records if record.id not in expired_ids]
        for record in expired:
            self._record_audit(
                record,
                action="expire",
                provenance=MemoryWriteProvenance(source="lifecycle_policy"),
                before_content=record.content,
            )
        return len(expired)

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
        resolution: str = "",
        evidence: str = "",
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
                resolution=resolution,
                evidence=evidence,
            )
        )
