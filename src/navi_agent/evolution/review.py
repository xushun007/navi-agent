from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import EvolutionCandidate, WorkflowEvolutionSample


@dataclass(slots=True)
class ReviewLoopSummary:
    candidate_count: int
    pending_candidate_count: int
    accepted_candidate_count: int
    rejected_candidate_count: int
    applied_candidate_count: int
    workflow_sample_count: int
    regressed_count: int
    improved_count: int
    unchanged_count: int
    top_candidate_targets: list[tuple[str, int]] = field(default_factory=list)
    pending_targets: list[tuple[str, int]] = field(default_factory=list)
    candidates_by_target: dict[str, list[EvolutionCandidate]] = field(default_factory=dict)
    top_regressed_workflows: list[tuple[str, int]] = field(default_factory=list)
    recommendation: str = ""


class ReviewLoopService:
    def summarize(
        self,
        *,
        candidates: list[EvolutionCandidate],
        workflow_samples: list[WorkflowEvolutionSample],
    ) -> ReviewLoopSummary:
        regressed = [sample for sample in workflow_samples if sample.status == "regressed"]
        improved = [sample for sample in workflow_samples if sample.status == "improved"]
        unchanged = [sample for sample in workflow_samples if sample.status == "unchanged"]
        pending_candidates = [candidate for candidate in candidates if candidate.status == "pending"]
        accepted_candidates = [candidate for candidate in candidates if candidate.status == "accepted"]
        rejected_candidates = [candidate for candidate in candidates if candidate.status == "rejected"]
        applied_candidates = [candidate for candidate in candidates if candidate.status == "applied"]

        target_counts = Counter(candidate.target for candidate in candidates)
        pending_target_counts = Counter(candidate.target for candidate in pending_candidates)
        workflow_counts = Counter(sample.workflow_name for sample in regressed)

        top_candidate_targets = target_counts.most_common(3)
        pending_targets = pending_target_counts.most_common(3)
        top_regressed_workflows = workflow_counts.most_common(3)
        candidates_by_target = self._group_candidates_by_target(candidates)

        recommendation = self._build_recommendation(
            top_candidate_targets=top_candidate_targets,
            pending_targets=pending_targets,
            top_regressed_workflows=top_regressed_workflows,
            regressed_count=len(regressed),
        )

        return ReviewLoopSummary(
            candidate_count=len(candidates),
            pending_candidate_count=len(pending_candidates),
            accepted_candidate_count=len(accepted_candidates),
            rejected_candidate_count=len(rejected_candidates),
            applied_candidate_count=len(applied_candidates),
            workflow_sample_count=len(workflow_samples),
            regressed_count=len(regressed),
            improved_count=len(improved),
            unchanged_count=len(unchanged),
            top_candidate_targets=top_candidate_targets,
            pending_targets=pending_targets,
            candidates_by_target=candidates_by_target,
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
    ) -> str:
        if regressed_count == 0:
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
