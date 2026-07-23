from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(slots=True)
class ReviewToolResultRecord:
    name: str
    status: str
    action: str = ""
    structured_content: dict = field(default_factory=dict)


@dataclass(slots=True)
class ReviewRunRecord:
    session_id: str
    trace_id: str
    user_id: str
    review_memory: bool
    review_skill: bool
    status: str
    review_run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    review_session_id: str = ""
    tool_results: list[ReviewToolResultRecord] = field(default_factory=list)
    memory_writes: list[dict] = field(default_factory=list)
    skill_writes: list[dict] = field(default_factory=list)
    error: str = ""


class JsonlReviewRunStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def add(self, record: ReviewRunRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def list_recent(self, limit: int | None = None) -> list[ReviewRunRecord]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        if limit is not None:
            lines = lines[-limit:]
        return [_review_run_from_dict(json.loads(line)) for line in reversed(lines)]


def _review_run_from_dict(payload: dict) -> ReviewRunRecord:
    tool_results = [
        ReviewToolResultRecord(**item) for item in payload.pop("tool_results", [])
    ]
    return ReviewRunRecord(
        **payload,
        tool_results=tool_results,
    )
