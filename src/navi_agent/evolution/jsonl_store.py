from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TypeVar

from .models import EvolutionCandidate, EvalCase

T = TypeVar("T")


class JsonlCandidateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def add(self, candidate: EvolutionCandidate) -> None:
        self._append(asdict(candidate))

    def list_recent(self, limit: int | None = None) -> list[EvolutionCandidate]:
        records = self._read_records(limit=limit)
        return [EvolutionCandidate(**record) for record in records]

    def get(self, candidate_id: str) -> EvolutionCandidate | None:
        for record in self._read_records():
            candidate = EvolutionCandidate(**record)
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def update_status(
        self,
        candidate_id: str,
        status: str,
        *,
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        records = self._read_records()
        updated: EvolutionCandidate | None = None
        new_records: list[dict] = []
        for record in records:
            candidate = EvolutionCandidate(**record)
            if candidate.candidate_id == candidate_id:
                candidate.status = status
                candidate.review_note = review_note
                updated = candidate
            new_records.append(asdict(candidate))
        if updated is None:
            return None
        self._write_records(new_records)
        return updated

    def _append(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _write_records(self, records: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def _read_records(self, *, limit: int | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        if limit is not None:
            lines = lines[-limit:]
        return [json.loads(line) for line in reversed(lines)]


class JsonlEvalCaseStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def add(self, eval_case: EvalCase) -> None:
        self._append(asdict(eval_case))

    def list_recent(self, limit: int | None = None) -> list[EvalCase]:
        records = self._read_records(limit=limit)
        return [EvalCase(**record) for record in records]

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
