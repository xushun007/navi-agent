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
        workflow_counts = Counter(sample.workflow_name for sample in regressed)

        top_candidate_targets = target_counts.most_common(3)
        top_regressed_workflows = workflow_counts.most_common(3)

        recommendation = self._build_recommendation(
            top_candidate_targets=top_candidate_targets,
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
            top_regressed_workflows=top_regressed_workflows,
            recommendation=recommendation,
        )

    @staticmethod
    def _build_recommendation(
        *,
        top_candidate_targets: list[tuple[str, int]],
        top_regressed_workflows: list[tuple[str, int]],
        regressed_count: int,
    ) -> str:
        if regressed_count == 0:
            return "No regressions detected in recent workflow comparisons."
        target = top_candidate_targets[0][0] if top_candidate_targets else "prompt"
        workflow = top_regressed_workflows[0][0] if top_regressed_workflows else "unknown-workflow"
        return f"Prioritize {target} improvements for {workflow} based on recent regressions."
