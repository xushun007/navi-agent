from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EvalSeed:
    key: int
    prompt: str
    instruction_id_list: list[str]
    kwargs: list[dict[str, Any]]
    session_id: str
    output: str
    pass_fail: bool | None
    notes: str | None = None


class EvalSeedStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def list_recent(self, limit: int | None = None) -> list[EvalSeed]:
        seeds = self._load()
        if limit is None:
            return seeds
        return seeds[-limit:]

    def describe(self) -> dict[str, object]:
        seeds = self._load()
        passed = [seed for seed in seeds if seed.pass_fail is True]
        failed = [seed for seed in seeds if seed.pass_fail is False]
        pending = [seed for seed in seeds if seed.pass_fail is None]
        return {
            "path": str(self._path),
            "exists": self._path.exists(),
            "count": len(seeds),
            "passed_count": len(passed),
            "failed_count": len(failed),
            "pending_count": len(pending),
            "keys": [seed.key for seed in seeds],
            "session_ids": [seed.session_id for seed in seeds],
        }

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self._path.exists():
            return [f"seed file not found: {self._path}"]
        for index, seed in enumerate(self._load_raw(), start=1):
            if not isinstance(seed.get("key"), int):
                issues.append(f"line {index}: key must be an integer")
            if not isinstance(seed.get("prompt"), str) or not seed.get("prompt", "").strip():
                issues.append(f"line {index}: prompt must be a non-empty string")
            if not isinstance(seed.get("instruction_id_list"), list):
                issues.append(f"line {index}: instruction_id_list must be a list")
            if not isinstance(seed.get("kwargs"), list):
                issues.append(f"line {index}: kwargs must be a list")
            if not isinstance(seed.get("session_id"), str) or not seed.get("session_id", "").strip():
                issues.append(f"line {index}: session_id must be a non-empty string")
            if not isinstance(seed.get("output"), str):
                issues.append(f"line {index}: output must be a string")
            if seed.get("pass_fail") not in {True, False, None}:
                issues.append(f"line {index}: pass_fail must be true false or null")
        return issues

    def _load(self) -> list[EvalSeed]:
        return [EvalSeed(**record) for record in self._load_raw()]

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records
