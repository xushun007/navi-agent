from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import EvolutionCandidate


@dataclass(frozen=True, slots=True)
class SkillProvenanceRecord:
    name: str
    origin: str
    created_at: str
    source_candidate_id: str | None = None
    source_session_id: str | None = None
    source_trace_id: str | None = None
    metadata: dict[str, Any] | None = None


class SkillProvenanceStore:
    def __init__(self, skills_root: Path) -> None:
        self._path = skills_root / ".provenance.json"

    def mark_agent_created(self, *, skill_name: str, candidate: EvolutionCandidate) -> SkillProvenanceRecord:
        metadata = candidate.metadata or {}
        record = SkillProvenanceRecord(
            name=skill_name,
            origin="agent",
            created_at=datetime.now(UTC).isoformat(),
            source_candidate_id=candidate.candidate_id,
            source_session_id=_optional_str(metadata.get("source_session_id")),
            source_trace_id=_optional_str(metadata.get("source_trace_id")),
            metadata={
                "candidate_target": candidate.target,
                "reviewer": _optional_str(metadata.get("reviewer")),
            },
        )
        records = self._read()
        records[skill_name] = asdict(record)
        self._write(records)
        return record

    def get(self, skill_name: str) -> SkillProvenanceRecord | None:
        payload = self._read().get(skill_name)
        if not isinstance(payload, dict):
            return None
        return SkillProvenanceRecord(**payload)

    def is_agent_created(self, skill_name: str) -> bool:
        record = self.get(skill_name)
        return record is not None and record.origin == "agent"

    def remove(self, skill_name: str) -> bool:
        records = self._read()
        if skill_name not in records:
            return False
        del records[skill_name]
        self._write(records)
        return True

    def list(self) -> list[SkillProvenanceRecord]:
        return [
            SkillProvenanceRecord(**payload)
            for _, payload in sorted(self._read().items())
            if isinstance(payload, dict)
        ]

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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
