from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TypeVar

from .models import EvolutionCandidate, WorkflowEvolutionSample

T = TypeVar("T")


class JsonlCandidateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def add(self, candidate: EvolutionCandidate) -> None:
        self._append(asdict(candidate))

    def list_recent(self, limit: int | None = None) -> list[EvolutionCandidate]:
        records = self._read_records(limit=limit)
        return [EvolutionCandidate(**record) for record in records]

    def _append(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _read_records(self, *, limit: int | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        if limit is not None:
            lines = lines[-limit:]
        return [json.loads(line) for line in reversed(lines)]


class JsonlWorkflowSampleStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def add(self, sample: WorkflowEvolutionSample) -> None:
        self._append(asdict(sample))

    def list_recent(self, limit: int | None = None) -> list[WorkflowEvolutionSample]:
        records = self._read_records(limit=limit)
        return [WorkflowEvolutionSample(**record) for record in records]

    def _append(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _read_records(self, *, limit: int | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        if limit is not None:
            lines = lines[-limit:]
        return [json.loads(line) for line in reversed(lines)]
