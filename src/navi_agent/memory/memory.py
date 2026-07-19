from __future__ import annotations

import uuid

from .models import MemoryRecord
from .validation import normalize_memory_content, validate_memory_content


class InMemoryMemoryStore:
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records = records or []

    def list_for_user(self, user_id: str) -> list[MemoryRecord]:
        return [record for record in self._records if record.user_id == user_id]

    def add_for_user(
        self,
        user_id: str,
        content: str,
        kind: str = "fact",
        target: str = "",
        source: str = "unknown",
        source_session_id: str = "",
    ) -> MemoryRecord:
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
                return record
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            kind=kind,
            content=content,
            target=target,
            source=source,
            source_session_id=source_session_id,
        )
        self._records.append(record)
        return record

    def get_for_user(self, user_id: str, record_id: str) -> MemoryRecord | None:
        for record in self._records:
            if record.user_id == user_id and record.id == record_id:
                return record
        return None

    def update_for_user(self, user_id: str, record_id: str, content: str) -> MemoryRecord | None:
        record = self.get_for_user(user_id, record_id)
        if record is None:
            return None
        validation_error = validate_memory_content(content)
        if validation_error:
            raise ValueError(validation_error)
        record.content = normalize_memory_content(content)
        return record

    def remove_for_user(self, user_id: str, record_id: str) -> bool:
        for index, record in enumerate(self._records):
            if record.user_id == user_id and record.id == record_id:
                self._records.pop(index)
                return True
        return False
