from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from navi_agent.telemetry import TraceStore

from .skills import FileSkillStore


@dataclass(frozen=True, slots=True)
class SkillUsageRecord:
    name: str
    description: str
    injected_count: int
    last_injected_at: str | None = None
    created_count: int = 0
    updated_count: int = 0
    archived_count: int = 0
    last_created_at: str | None = None
    last_updated_at: str | None = None
    last_archived_at: str | None = None


@dataclass(slots=True)
class SkillUsageSidecarRecord:
    name: str
    created_count: int = 0
    updated_count: int = 0
    archived_count: int = 0
    last_created_at: str | None = None
    last_updated_at: str | None = None
    last_archived_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillUsageStore:
    def __init__(self, skills_root: Path) -> None:
        self._path = skills_root / ".usage.json"

    def record_create(self, skill_name: str) -> SkillUsageSidecarRecord:
        return self._record(skill_name, count_field="created_count", time_field="last_created_at")

    def record_update(self, skill_name: str) -> SkillUsageSidecarRecord:
        return self._record(skill_name, count_field="updated_count", time_field="last_updated_at")

    def record_archive(self, skill_name: str) -> SkillUsageSidecarRecord:
        return self._record(skill_name, count_field="archived_count", time_field="last_archived_at")

    def get(self, skill_name: str) -> SkillUsageSidecarRecord | None:
        payload = self._read().get(skill_name)
        if not isinstance(payload, dict):
            return None
        return SkillUsageSidecarRecord(**payload)

    def list(self) -> list[SkillUsageSidecarRecord]:
        return [
            SkillUsageSidecarRecord(**payload)
            for _, payload in sorted(self._read().items())
            if isinstance(payload, dict)
        ]

    def _record(
        self,
        skill_name: str,
        *,
        count_field: str,
        time_field: str,
    ) -> SkillUsageSidecarRecord:
        records = self._read()
        payload = records.get(skill_name) or {"name": skill_name}
        record = SkillUsageSidecarRecord(**payload)
        setattr(record, count_field, int(getattr(record, count_field)) + 1)
        setattr(record, time_field, datetime.now(UTC).isoformat())
        records[skill_name] = asdict(record)
        self._write(records)
        return record

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(name): value for name, value in payload.items() if isinstance(value, dict)}

    def _write(self, records: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._path.parent,
            delete=False,
        ) as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self._path)


class SkillUsageService:
    def __init__(
        self,
        *,
        skill_store: FileSkillStore,
        trace_store: TraceStore,
        usage_store: SkillUsageStore | None = None,
    ) -> None:
        self._skill_store = skill_store
        self._trace_store = trace_store
        self._usage_store = usage_store

    def summarize(self, *, trace_limit: int | None = None) -> list[SkillUsageRecord]:
        skills = self._skill_store.list()
        usage = {
            skill.name: {
                "count": 0,
                "last_injected_at": None,
            }
            for skill in skills
        }
        for trace in self._trace_store.list_traces(limit=trace_limit):
            timestamp = trace.completed_at or trace.started_at
            for skill_name in trace.injected_skill_names:
                if skill_name not in usage:
                    usage[skill_name] = {
                        "count": 0,
                        "last_injected_at": None,
                    }
                usage[skill_name]["count"] += 1
                if timestamp and (
                    usage[skill_name]["last_injected_at"] is None
                    or timestamp > usage[skill_name]["last_injected_at"]
                ):
                    usage[skill_name]["last_injected_at"] = timestamp

        descriptions = {skill.name: skill.description for skill in skills}
        sidecar = {record.name: record for record in self._usage_store.list()} if self._usage_store is not None else {}
        records = [
            SkillUsageRecord(
                name=name,
                description=descriptions.get(name, ""),
                injected_count=int(values["count"]),
                last_injected_at=values["last_injected_at"],
                created_count=sidecar[name].created_count if name in sidecar else 0,
                updated_count=sidecar[name].updated_count if name in sidecar else 0,
                archived_count=sidecar[name].archived_count if name in sidecar else 0,
                last_created_at=sidecar[name].last_created_at if name in sidecar else None,
                last_updated_at=sidecar[name].last_updated_at if name in sidecar else None,
                last_archived_at=sidecar[name].last_archived_at if name in sidecar else None,
            )
            for name, values in {**{record.name: {"count": 0, "last_injected_at": None} for record in sidecar.values()}, **usage}.items()
        ]
        return sorted(records, key=lambda record: (-record.injected_count, record.name))
