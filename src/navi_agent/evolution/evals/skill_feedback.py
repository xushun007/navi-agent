from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from ..skills.governance import (
    SkillGovernanceService,
    SkillHumanFeedback,
    SkillHumanReview,
)


_PREFERENCES = {"baseline", "variant", "tie"}
_ATTRIBUTIONS = {
    "",
    "skill_selection",
    "instruction_quality",
    "tool_use",
    "factuality",
    "completeness",
    "other",
}


@dataclass(frozen=True, slots=True)
class SkillFeedbackImport:
    feedback: SkillHumanFeedback
    preference_counts: dict[str, int]


class SkillFeedbackImportService:
    def __init__(self, governance: SkillGovernanceService) -> None:
        self._governance = governance

    def import_feedback(
        self,
        draft_id: str,
        *,
        report_path: Path,
        feedback_path: Path,
    ) -> SkillFeedbackImport:
        report_file = report_path / "run.json" if report_path.is_dir() else report_path
        report_bytes = report_file.read_bytes()
        feedback_bytes = feedback_path.read_bytes()
        report = json.loads(report_bytes)
        payload = json.loads(feedback_bytes)
        if not isinstance(report, dict) or not isinstance(payload, dict):
            raise ValueError("skill feedback and report must be JSON objects")

        evidence = self._match_evidence(draft_id, report_file.parent, report)
        schema_version = payload.get("schema_version")
        if schema_version != 1:
            raise ValueError("unsupported skill feedback schema_version")
        workflow_name = _required_text(payload, "workflow_name")
        if workflow_name != report.get("workflow_name"):
            raise ValueError("skill feedback workflow does not match report")
        exported_at = _required_text(payload, "exported_at")
        reviews = _load_reviews(payload.get("reviews"))
        expected_tasks = [
            str(item.get("task_name") or "")
            for item in report.get("step_comparisons", [])
            if isinstance(item, dict)
        ]
        actual_tasks = [review.task_name for review in reviews]
        if len(actual_tasks) != len(set(actual_tasks)):
            raise ValueError("skill feedback contains duplicate task names")
        if set(actual_tasks) != set(expected_tasks) or len(actual_tasks) != len(expected_tasks):
            raise ValueError("skill feedback task names do not match report")

        feedback = self._governance.record_human_feedback(
            draft_id,
            evidence_id=evidence.evidence_id,
            schema_version=schema_version,
            workflow_name=workflow_name,
            exported_at=exported_at,
            report_hash=_hash(report_bytes),
            feedback_hash=_hash(feedback_bytes),
            source_path=str(feedback_path.resolve()),
            reviews=reviews,
        )
        counts = {preference: 0 for preference in sorted(_PREFERENCES)}
        for review in reviews:
            counts[review.preference] += 1
        return SkillFeedbackImport(feedback=feedback, preference_counts=counts)

    def _match_evidence(self, draft_id: str, report_path: Path, report: dict):
        eval_case = report.get("eval_case")
        metadata = eval_case.get("metadata") if isinstance(eval_case, dict) else None
        if not isinstance(metadata, dict) or metadata.get("draft_id") != draft_id:
            raise ValueError("skill evaluation report does not match draft")
        report_skill = str(metadata.get("skill_name") or "")
        report_cases = str(metadata.get("case_fingerprint") or "")
        source_session_id = str(report.get("source_session_id") or "")
        replay_session_id = str(report.get("replay_session_id") or "")
        resolved_report = report_path.resolve()
        for evidence in self._governance.list_evaluation_evidence(draft_id):
            if (
                Path(evidence.report_path).resolve() == resolved_report
                and evidence.skill_name == report_skill
                and evidence.case_fingerprint == report_cases
                and evidence.source_session_id == source_session_id
                and evidence.replay_session_id == replay_session_id
            ):
                return evidence
        raise ValueError("report is not bound to recorded skill evaluation evidence")


def _load_reviews(value: object) -> tuple[SkillHumanReview, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("skill feedback requires non-empty reviews")
    reviews = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("skill feedback reviews must be objects")
        task_name = _required_text(item, "task_name")
        preference = _required_text(item, "preference")
        attribution = str(item.get("attribution") or "").strip()
        notes = str(item.get("notes") or "").strip()
        if preference not in _PREFERENCES:
            raise ValueError(f"invalid skill feedback preference: {preference}")
        if attribution not in _ATTRIBUTIONS:
            raise ValueError(f"invalid skill feedback attribution: {attribution}")
        reviews.append(SkillHumanReview(task_name, preference, attribution, notes))
    return tuple(reviews)


def _required_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"skill feedback requires {key}")
    return value.strip()


def _hash(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"
