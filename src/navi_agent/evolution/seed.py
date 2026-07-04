from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import asdict
from datetime import datetime, timezone
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

    @property
    def path(self) -> Path:
        return self._path

    def append(self, seed: EvalSeed) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(seed), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

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


@dataclass(frozen=True, slots=True)
class EvalSeedReportRecord:
    seed_path: str
    report_path: str
    count: int
    passed_count: int
    failed_count: int
    pending_count: int
    pass_rate: float
    created_at: str


class EvalSeedReportWriter:
    def __init__(self, reports_root: Path) -> None:
        self._reports_root = reports_root

    def write_report(self, *, seed_store: EvalSeedStore) -> Path:
        report_dir = self._new_report_dir()
        seeds = seed_store.list_recent(limit=None)
        info = seed_store.describe()
        payload = {
            "seed_path": info["path"],
            "count": info["count"],
            "passed_count": info["passed_count"],
            "failed_count": info["failed_count"],
            "pending_count": info["pending_count"],
            "pass_rate": self._pass_rate(info["count"], info["passed_count"]),
            "seeds": [asdict(seed) for seed in seeds],
        }
        (report_dir / "run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (report_dir / "REPORT.md").write_text(
            self._build_markdown(payload),
            encoding="utf-8",
        )
        return report_dir

    def _new_report_dir(self) -> Path:
        self._reports_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        report_dir = self._reports_root / timestamp
        suffix = 1
        while report_dir.exists():
            report_dir = self._reports_root / f"{timestamp}-{suffix}"
            suffix += 1
        report_dir.mkdir(parents=True, exist_ok=False)
        return report_dir

    @staticmethod
    def _pass_rate(count: int, passed_count: int) -> float:
        if count <= 0:
            return 0.0
        return round(passed_count / count, 3)

    @staticmethod
    def _build_markdown(payload: dict[str, object]) -> str:
        lines = [
            "# Eval seed report",
            "",
            "## Summary",
            f"- seed path: `{payload['seed_path']}`",
            f"- count: `{payload['count']}`",
            f"- passed: `{payload['passed_count']}`",
            f"- failed: `{payload['failed_count']}`",
            f"- pending: `{payload['pending_count']}`",
            f"- pass rate: `{payload['pass_rate']}`",
            "",
            "## Seeds",
        ]
        for seed in payload.get("seeds", []):
            if not isinstance(seed, dict):
                continue
            status = "pending"
            if seed.get("pass_fail") is True:
                status = "pass"
            elif seed.get("pass_fail") is False:
                status = "fail"
            lines.extend(
                [
                    f"- `{seed.get('key')}` [{status}] `{seed.get('session_id')}`",
                    f"  prompt: {seed.get('prompt', '')}",
                    f"  notes: {seed.get('notes', '')}",
                ]
            )
        return "\n".join(lines) + "\n"


class EvalSeedReportStore:
    def __init__(self, reports_root: Path) -> None:
        self._reports_root = reports_root

    def get_latest(self) -> EvalSeedReportRecord | None:
        reports = self.list_recent(limit=1)
        if not reports:
            return None
        return reports[0]

    def list_recent(self, limit: int | None = None) -> list[EvalSeedReportRecord]:
        if not self._reports_root.exists():
            return []
        run_dirs = [path for path in self._reports_root.iterdir() if path.is_dir() and (path / "run.json").exists()]
        run_dirs.sort(key=lambda path: path.name, reverse=True)
        if limit is not None:
            run_dirs = run_dirs[:limit]
        records: list[EvalSeedReportRecord] = []
        for run_dir in run_dirs:
            record = self._load_record(run_dir)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _load_record(run_dir: Path) -> EvalSeedReportRecord | None:
        try:
            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        count = int(payload.get("count", 0))
        passed_count = int(payload.get("passed_count", 0))
        failed_count = int(payload.get("failed_count", 0))
        pending_count = int(payload.get("pending_count", 0))
        pass_rate = EvalSeedReportWriter._pass_rate(count, passed_count)
        return EvalSeedReportRecord(
            seed_path=str(payload.get("seed_path", "")),
            report_path=str(run_dir),
            count=count,
            passed_count=passed_count,
            failed_count=failed_count,
            pending_count=pending_count,
            pass_rate=pass_rate,
            created_at=run_dir.name,
        )
