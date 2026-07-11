from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from .models import MemoryRecord


class FileMemoryStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def list_for_user(self, user_id: str) -> list[MemoryRecord]:
        return [record for record in self._read_all() if record.user_id == user_id]

    def add_for_user(self, user_id: str, content: str, kind: str = "fact") -> MemoryRecord:
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            kind=self._normalize_kind(kind),
            content=content,
        )
        records = self._read_all()
        records.append(record)
        self._write_all(records)
        return record

    def get_for_user(self, user_id: str, record_id: str) -> MemoryRecord | None:
        for record in self.list_for_user(user_id):
            if record.id == record_id:
                return record
        return None

    def update_for_user(self, user_id: str, record_id: str, content: str) -> MemoryRecord | None:
        records = self._read_all()
        updated = None
        for record in records:
            if record.user_id == user_id and record.id == record_id:
                record.content = content
                updated = record
                break
        if updated is None:
            return None
        self._write_all(records)
        return updated

    def remove_for_user(self, user_id: str, record_id: str) -> bool:
        records = self._read_all()
        remaining = [
            record
            for record in records
            if not (record.user_id == user_id and record.id == record_id)
        ]
        if len(remaining) == len(records):
            return False
        self._write_all(remaining)
        return True

    def _read_all(self) -> list[MemoryRecord]:
        records = []
        for path in [self._memory_path, self._user_path]:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    records.append(MemoryRecord(**json.loads(line)))
        return records

    def _write_all(self, records: list[MemoryRecord]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        grouped = {
            self._memory_path: [record for record in records if record.kind != "preference"],
            self._user_path: [record for record in records if record.kind == "preference"],
        }
        for path, items in grouped.items():
            with path.open("w", encoding="utf-8") as handle:
                for record in items:
                    handle.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True))
                    handle.write("\n")

    @property
    def _memory_path(self) -> Path:
        return self._root / "MEMORY.md"

    @property
    def _user_path(self) -> Path:
        return self._root / "USER.md"

    @staticmethod
    def _normalize_kind(kind: str) -> str:
        kind = kind.strip().lower()
        if kind not in {"fact", "preference", "task"}:
            return "fact"
        return kind
