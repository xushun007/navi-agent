from __future__ import annotations

from contextlib import contextmanager
import re
import tempfile
import uuid
from pathlib import Path

from .models import MemoryRecord
from .search import search_memories
from .validation import normalize_memory_content, validate_memory_content

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

_ENTRY_RE = re.compile(
    r"^- \[(?P<kind>[a-z]+)\]\s+(?P<content>.*)\n"
    r"  <!-- id:(?P<id>[^ ]+) user:(?P<user_id>[^ ]+)"
    r"(?: source:(?P<source>[^ ]+))?"
    r"(?: session:(?P<source_session_id>[^ ]+))?"
    r" -->$",
    re.MULTILINE,
)


class FileMemoryStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def list_for_user(self, user_id: str) -> list[MemoryRecord]:
        return [record for record in self._read_all() if record.user_id == user_id]

    def search_for_user(self, user_id: str, query: str, limit: int) -> list[MemoryRecord]:
        return search_memories(self.list_for_user(user_id), query=query, limit=limit)

    def add_for_user(
        self,
        user_id: str,
        content: str,
        kind: str = "fact",
        target: str = "",
        source: str = "unknown",
        source_session_id: str = "",
    ) -> MemoryRecord:
        normalized_kind = self._normalize_kind(kind)
        normalized_target = self._normalize_target(target, kind=normalized_kind)
        content = normalize_memory_content(content)
        validation_error = validate_memory_content(content)
        if validation_error:
            raise ValueError(validation_error)
        with self._file_lock():
            records = self._read_all()
            for existing in records:
                if (
                    existing.user_id == user_id
                    and existing.kind == normalized_kind
                    and existing.target == normalized_target
                    and normalize_memory_content(existing.content) == content
                ):
                    return existing
            record = MemoryRecord(
                id=uuid.uuid4().hex[:12],
                user_id=user_id,
                kind=normalized_kind,
                content=content,
                target=normalized_target,
                source=self._single_line(source) or "unknown",
                source_session_id=self._single_line(source_session_id),
            )
            records.append(record)
            self._write_all(records)
            return record

    def get_for_user(self, user_id: str, record_id: str) -> MemoryRecord | None:
        for record in self.list_for_user(user_id):
            if record.id == record_id:
                return record
        return None

    def update_for_user(self, user_id: str, record_id: str, content: str) -> MemoryRecord | None:
        validation_error = validate_memory_content(content)
        if validation_error:
            raise ValueError(validation_error)
        with self._file_lock():
            records = self._read_all()
            updated = None
            for record in records:
                if record.user_id == user_id and record.id == record_id:
                    record.content = normalize_memory_content(content)
                    updated = record
                    break
            if updated is None:
                return None
            self._write_all(records)
            return updated

    def remove_for_user(self, user_id: str, record_id: str) -> bool:
        with self._file_lock():
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
            target = "user" if path == self._user_path else "memory"
            text = path.read_text(encoding="utf-8")
            for match in _ENTRY_RE.finditer(text):
                records.append(
                    MemoryRecord(
                        id=match.group("id"),
                        user_id=match.group("user_id"),
                        kind=self._normalize_kind(match.group("kind")),
                        content=match.group("content").strip(),
                        target=target,
                        source=match.group("source") or "unknown",
                        source_session_id=match.group("source_session_id") or "",
                    )
                )
        return records

    def _write_all(self, records: list[MemoryRecord]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        grouped = {
            self._memory_path: [record for record in records if record.target == "memory"],
            self._user_path: [record for record in records if record.target == "user"],
        }
        for path, items in grouped.items():
            self._write_memory_file(path, items)

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

    @staticmethod
    def _normalize_target(target: str, *, kind: str = "fact") -> str:
        target = target.strip().lower()
        if target in {"memory", "user"}:
            return target
        if kind.strip().lower() == "preference":
            return "user"
        return "memory"

    @staticmethod
    def _single_line(content: str) -> str:
        return " ".join(content.strip().split())

    @contextmanager
    def _file_lock(self):
        self._root.mkdir(parents=True, exist_ok=True)
        lock_path = self._root / ".memory.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _write_memory_file(path: Path, records: list[MemoryRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(f"# {path.stem.title()}\n\n")
            for record in records:
                handle.write(f"- [{record.kind}] {FileMemoryStore._single_line(record.content)}\n")
                handle.write(
                    f"  <!-- id:{record.id} user:{record.user_id}"
                    f" source:{FileMemoryStore._single_line(record.source) or 'unknown'}"
                    f"{f' session:{FileMemoryStore._single_line(record.source_session_id)}' if record.source_session_id else ''}"
                    " -->\n"
                )
            if records:
                handle.write("\n")
        temp_path.replace(path)
