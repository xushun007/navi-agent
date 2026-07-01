from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import EvolutionCandidate, EvalCase


@dataclass(slots=True)
class ReviewLoopSummary:
    candidate_count: int
    active_candidate_count: int
    pending_candidate_count: int
    accepted_candidate_count: int
    rejected_candidate_count: int
    applied_candidate_count: int
    verified_candidate_count: int
    no_improvement_candidate_count: int
    regressed_after_apply_candidate_count: int
    superseded_candidate_count: int
    archived_candidate_count: int
    eval_case_count: int
    regressed_count: int
    improved_count: int
    unchanged_count: int
    top_candidate_targets: list[tuple[str, int]] = field(default_factory=list)
    pending_targets: list[tuple[str, int]] = field(default_factory=list)
    candidates_by_target: dict[str, list[EvolutionCandidate]] = field(default_factory=dict)
    pending_queue: list[EvolutionCandidate] = field(default_factory=list)
    pending_work_items: list[dict[str, object]] = field(default_factory=list)
    top_regressed_workflows: list[tuple[str, int]] = field(default_factory=list)
    recommendation: str = ""


class ReviewLoopService:
    _RETIRED_CANDIDATE_STATUSES = {
        "rejected",
        "verified",
        "no_improvement",
        "regressed_after_apply",
        "superseded",
        "archived",
    }

    def summarize(
        self,
        *,
        candidates: list[EvolutionCandidate],
        eval_cases: list[EvalCase],
    ) -> ReviewLoopSummary:
        regressed = [eval_case for eval_case in eval_cases if eval_case.status == "regressed"]
        improved = [eval_case for eval_case in eval_cases if eval_case.status == "improved"]
        unchanged = [eval_case for eval_case in eval_cases if eval_case.status == "unchanged"]
        pending_candidates = [candidate for candidate in candidates if candidate.status == "pending"]
        accepted_candidates = [candidate for candidate in candidates if candidate.status == "accepted"]
        rejected_candidates = [candidate for candidate in candidates if candidate.status == "rejected"]
        applied_candidates = [candidate for candidate in candidates if candidate.status == "applied"]
        verified_candidates = [candidate for candidate in candidates if candidate.status == "verified"]
        no_improvement_candidates = [candidate for candidate in candidates if candidate.status == "no_improvement"]
        regressed_after_apply_candidates = [
            candidate for candidate in candidates if candidate.status == "regressed_after_apply"
        ]
        superseded_candidates = [candidate for candidate in candidates if candidate.status == "superseded"]
        archived_candidates = [candidate for candidate in candidates if candidate.status == "archived"]
        active_candidates = [
            candidate
            for candidate in candidates
            if candidate.status not in self._RETIRED_CANDIDATE_STATUSES
        ]

        target_counts = Counter(candidate.target for candidate in active_candidates)
        pending_target_counts = Counter(candidate.target for candidate in pending_candidates)
        workflow_counts = Counter(eval_case.workflow_name for eval_case in regressed)

        top_candidate_targets = target_counts.most_common(3)
        pending_targets = pending_target_counts.most_common(3)
        top_regressed_workflows = workflow_counts.most_common(3)
        candidates_by_target = self._group_candidates_by_target(active_candidates)
        pending_queue = self._build_pending_queue(pending_candidates)
        pending_work_items = self._build_pending_work_items(pending_queue)

        recommendation = self._build_recommendation(
            top_candidate_targets=top_candidate_targets,
            pending_targets=pending_targets,
            top_regressed_workflows=top_regressed_workflows,
            regressed_count=len(regressed),
            verified_count=len(verified_candidates),
            no_improvement_count=len(no_improvement_candidates),
            regressed_after_apply_count=len(regressed_after_apply_candidates),
        )

        return ReviewLoopSummary(
            candidate_count=len(candidates),
            active_candidate_count=len(active_candidates),
            pending_candidate_count=len(pending_candidates),
            accepted_candidate_count=len(accepted_candidates),
            rejected_candidate_count=len(rejected_candidates),
            applied_candidate_count=len(applied_candidates),
            verified_candidate_count=len(verified_candidates),
            no_improvement_candidate_count=len(no_improvement_candidates),
            regressed_after_apply_candidate_count=len(regressed_after_apply_candidates),
            superseded_candidate_count=len(superseded_candidates),
            archived_candidate_count=len(archived_candidates),
            eval_case_count=len(eval_cases),
            regressed_count=len(regressed),
            improved_count=len(improved),
            unchanged_count=len(unchanged),
            top_candidate_targets=top_candidate_targets,
            pending_targets=pending_targets,
            candidates_by_target=candidates_by_target,
            pending_queue=pending_queue,
            pending_work_items=pending_work_items,
            top_regressed_workflows=top_regressed_workflows,
            recommendation=recommendation,
        )

    @staticmethod
    def _build_recommendation(
        *,
        top_candidate_targets: list[tuple[str, int]],
        pending_targets: list[tuple[str, int]],
        top_regressed_workflows: list[tuple[str, int]],
        regressed_count: int,
        verified_count: int,
        no_improvement_count: int,
        regressed_after_apply_count: int,
    ) -> str:
        if regressed_after_apply_count:
            workflow = top_regressed_workflows[0][0] if top_regressed_workflows else "recent prompt validations"
            return f"Inspect regressed_after_apply candidates before applying more prompt changes to {workflow}."
        if regressed_count == 0:
            if no_improvement_count:
                return "Review no_improvement candidates and replace stale prompt overlays before expanding the workflow set."
            if verified_count:
                return "Promote verified prompt changes into the baseline before expanding the workflow set."
            if pending_targets:
                target = pending_targets[0][0]
                return f"Review pending {target} candidates before expanding the workflow set."
            return "No regressions detected in recent workflow comparisons."
        target = pending_targets[0][0] if pending_targets else top_candidate_targets[0][0] if top_candidate_targets else "prompt"
        workflow = top_regressed_workflows[0][0] if top_regressed_workflows else "unknown-workflow"
        return f"Prioritize {target} improvements for {workflow} based on recent regressions."

    @staticmethod
    def _group_candidates_by_target(
        candidates: list[EvolutionCandidate],
    ) -> dict[str, list[EvolutionCandidate]]:
        grouped: dict[str, list[EvolutionCandidate]] = {}
        for candidate in candidates:
            grouped.setdefault(candidate.target, []).append(candidate)
        for target in grouped:
            grouped[target] = sorted(
                grouped[target],
                key=lambda candidate: (
                    0 if candidate.status == "pending" else 1,
                    getattr(candidate, "reviewed_at", None) or "",
                    candidate.candidate_id,
                ),
            )
        return grouped

    @staticmethod
    def _build_pending_queue(
        pending_candidates: list[EvolutionCandidate],
    ) -> list[EvolutionCandidate]:
        return sorted(
            pending_candidates,
            key=lambda candidate: (
                0 if ReviewLoopService._candidate_metadata(candidate).get("workflow_status") == "regressed" else 1,
                ReviewLoopService._workflow_score_delta(candidate),
                ReviewLoopService._step_score_delta(candidate),
                candidate.candidate_id,
            ),
        )

    @staticmethod
    def _build_pending_work_items(
        pending_queue: list[EvolutionCandidate],
    ) -> list[dict[str, object]]:
        work_items: list[dict[str, object]] = []
        for candidate in pending_queue:
            metadata = ReviewLoopService._candidate_metadata(candidate)
            work_items.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "target": candidate.target,
                    "summary": candidate.summary,
                    "rationale": getattr(candidate, "rationale", ""),
                    "workflow_name": metadata.get("workflow_name"),
                    "workflow_status": metadata.get("workflow_status"),
                    "workflow_score_delta": metadata.get("workflow_score_delta"),
                    "task_name": metadata.get("task_name"),
                    "source_session_id": metadata.get("source_session_id"),
                    "replay_session_id": metadata.get("replay_session_id"),
                    "source_trace_id": metadata.get("source_trace_id"),
                    "replay_trace_id": metadata.get("replay_trace_id"),
                    "step_score_delta": metadata.get("step_score_delta"),
                    "signals": list(metadata.get("signals", [])) if isinstance(metadata.get("signals"), list) else [],
                }
            )
        return work_items

    @staticmethod
    def _workflow_score_delta(candidate: EvolutionCandidate) -> float:
        value = ReviewLoopService._candidate_metadata(candidate).get("workflow_score_delta")
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    @staticmethod
    def _step_score_delta(candidate: EvolutionCandidate) -> float:
        value = ReviewLoopService._candidate_metadata(candidate).get("step_score_delta")
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    @staticmethod
    def _candidate_metadata(candidate: EvolutionCandidate) -> dict:
        metadata = getattr(candidate, "metadata", None)
        if isinstance(metadata, dict):
            return metadata
        return {}
