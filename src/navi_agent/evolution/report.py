from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .review import ReviewLoopSummary

if TYPE_CHECKING:
    from navi_agent.smoke import SmokeWorkflowComparison


@dataclass(frozen=True, slots=True)
class EvolutionReportRecord:
    workflow_name: str
    status: str
    score_delta: float
    report_path: Path
    candidate_target: str | None = None
    candidate_id: str | None = None
    candidate_status: str | None = None
    created_at: str | None = None


class EvolutionReportWriter:
    def __init__(self, reports_root: Path) -> None:
        self._reports_root = reports_root

    def write_workflow_comparison_report(
        self,
        *,
        comparison: SmokeWorkflowComparison,
        review_summary: ReviewLoopSummary | None = None,
    ) -> Path:
        run_dir = self._new_run_dir()
        payload = self._build_payload(
            comparison=comparison,
            review_summary=review_summary,
        )
        (run_dir / "run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (run_dir / "REPORT.md").write_text(
            self._build_markdown(
                comparison=comparison,
                review_summary=review_summary,
            ),
            encoding="utf-8",
        )
        return run_dir

    def _new_run_dir(self) -> Path:
        self._reports_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_dir = self._reports_root / timestamp
        suffix = 1
        while run_dir.exists():
            run_dir = self._reports_root / f"{timestamp}-{suffix}"
            suffix += 1
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    @staticmethod
    def _build_payload(
        *,
        comparison: SmokeWorkflowComparison,
        review_summary: ReviewLoopSummary | None,
    ) -> dict:
        return {
            "workflow_name": comparison.workflow_name,
            "source_session_id": comparison.source_session_id,
            "replay_session_id": comparison.replay_session_id,
            "source_average_score": comparison.source_average_score,
            "replay_average_score": comparison.replay_average_score,
            "score_delta": comparison.score_delta,
            "workflow_sample": asdict(comparison.sample),
            "candidate": asdict(comparison.candidate) if comparison.candidate is not None else None,
            "step_comparisons": [
                {
                    "task_name": step.task_name,
                    "source_trace_id": step.source_step.trace_id,
                    "replay_trace_id": step.replay_step.trace_id,
                    "source_score": step.source_evaluation.score if step.source_evaluation is not None else None,
                    "replay_score": step.replay_evaluation.score if step.replay_evaluation is not None else None,
                    "score_delta": step.score_delta,
                }
                for step in comparison.step_comparisons
            ],
            "review_summary": asdict(review_summary) if review_summary is not None else None,
        }

    @staticmethod
    def _build_markdown(
        *,
        comparison: SmokeWorkflowComparison,
        review_summary: ReviewLoopSummary | None,
    ) -> str:
        lines = [
            "# Evolution workflow comparison",
            "",
            "## Summary",
            f"- workflow: `{comparison.workflow_name}`",
            f"- source session: `{comparison.source_session_id}`",
            f"- replay session: `{comparison.replay_session_id}`",
            f"- status: `{comparison.sample.status}`",
            f"- source average score: `{comparison.source_average_score}`",
            f"- replay average score: `{comparison.replay_average_score}`",
            f"- score delta: `{comparison.score_delta}`",
            "",
            "## Step comparisons",
        ]
        for step in comparison.step_comparisons:
            lines.extend(
                [
                    f"- `{step.task_name}`",
                    f"  source trace: `{step.source_step.trace_id or 'n/a'}`",
                    f"  replay trace: `{step.replay_step.trace_id or 'n/a'}`",
                    f"  score delta: `{step.score_delta}`",
                ]
            )
        if comparison.candidate is not None:
            lines.extend(
                [
                    "",
                    "## Candidate",
                    f"- id: `{comparison.candidate.candidate_id}`",
                    f"- status: `{comparison.candidate.status}`",
                    f"- target: `{comparison.candidate.target}`",
                    f"- summary: {comparison.candidate.summary}",
                    f"- rationale: {comparison.candidate.rationale}",
                ]
            )
        if review_summary is not None:
            lines.extend(
                [
                    "",
                    "## Review loop",
                    f"- candidate count: `{review_summary.candidate_count}`",
                    f"- workflow sample count: `{review_summary.workflow_sample_count}`",
                    f"- regressed count: `{review_summary.regressed_count}`",
                    f"- improved count: `{review_summary.improved_count}`",
                    f"- unchanged count: `{review_summary.unchanged_count}`",
                    f"- recommendation: {review_summary.recommendation}",
                ]
            )
        return "\n".join(lines) + "\n"


class EvolutionReportStore:
    def __init__(self, reports_root: Path) -> None:
        self._reports_root = reports_root

    def get_latest(self) -> EvolutionReportRecord | None:
        reports = self.list_recent(limit=1)
        if not reports:
            return None
        return reports[0]

    def list_recent(self, limit: int | None = None) -> list[EvolutionReportRecord]:
        if not self._reports_root.exists():
            return []
        run_dirs = [path for path in self._reports_root.iterdir() if path.is_dir() and (path / "run.json").exists()]
        run_dirs.sort(key=lambda path: path.name, reverse=True)
        if limit is not None:
            run_dirs = run_dirs[:limit]
        records: list[EvolutionReportRecord] = []
        for run_dir in run_dirs:
            record = self._load_record(run_dir)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _load_record(run_dir: Path) -> EvolutionReportRecord | None:
        try:
            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        sample = payload.get("workflow_sample") or {}
        candidate = payload.get("candidate") or {}
        return EvolutionReportRecord(
            workflow_name=str(payload.get("workflow_name", "")),
            status=str(sample.get("status", "")),
            score_delta=float(payload.get("score_delta", 0.0)),
            report_path=run_dir,
            candidate_target=candidate.get("target") if isinstance(candidate, dict) else None,
            candidate_id=candidate.get("candidate_id") if isinstance(candidate, dict) else None,
            candidate_status=candidate.get("status") if isinstance(candidate, dict) else None,
            created_at=run_dir.name,
        )
