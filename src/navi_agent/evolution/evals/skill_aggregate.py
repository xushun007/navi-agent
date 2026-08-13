from __future__ import annotations

from dataclasses import dataclass

from ..skills.governance import SkillGovernanceService


@dataclass(frozen=True, slots=True)
class SkillEvaluationAggregate:
    draft_id: str
    status: str
    reason: str
    run_count: int
    reviewed_run_count: int
    machine_passed_run_count: int
    preference_counts: dict[str, int]


class SkillEvaluationAggregateService:
    """Summarize repeated Skill evidence without changing governance state."""

    def __init__(
        self,
        governance: SkillGovernanceService,
        *,
        minimum_runs: int = 3,
    ) -> None:
        self._governance = governance
        self._minimum_runs = minimum_runs

    def aggregate(self, draft_id: str) -> SkillEvaluationAggregate:
        evidence = self._governance.list_evaluation_evidence(draft_id)
        feedback = self._governance.list_human_feedback(draft_id)
        counts = {"baseline": 0, "tie": 0, "variant": 0}
        feedback_by_evidence: dict[str, list] = {}
        for item in feedback:
            feedback_by_evidence.setdefault(item.evidence_id, []).append(item)
            for review in item.reviews:
                counts[review.preference] += 1

        reviewed_runs = sum(
            1 for item in evidence if len(feedback_by_evidence.get(item.evidence_id, [])) == 1
        )
        machine_passed = sum(
            1
            for item in evidence
            if item.evaluation_results and all(result.passed for result in item.evaluation_results)
        )
        status, reason = self._decision(
            evidence=evidence,
            feedback_by_evidence=feedback_by_evidence,
            counts=counts,
            reviewed_runs=reviewed_runs,
            machine_passed=machine_passed,
        )
        return SkillEvaluationAggregate(
            draft_id=draft_id,
            status=status,
            reason=reason,
            run_count=len(evidence),
            reviewed_run_count=reviewed_runs,
            machine_passed_run_count=machine_passed,
            preference_counts=counts,
        )

    def _decision(
        self,
        *,
        evidence: list,
        feedback_by_evidence: dict[str, list],
        counts: dict[str, int],
        reviewed_runs: int,
        machine_passed: int,
    ) -> tuple[str, str]:
        if len(evidence) < self._minimum_runs:
            return "inconclusive", f"requires at least {self._minimum_runs} evaluation runs"
        fingerprints = {
            (item.skill_content_hash, item.case_fingerprint, item.model_config_fingerprint)
            for item in evidence
        }
        if len(fingerprints) != 1 or any(not value for value in next(iter(fingerprints))):
            return "inconclusive", "evaluation runs do not share complete comparable fingerprints"
        if any(len(feedback_by_evidence.get(item.evidence_id, [])) > 1 for item in evidence):
            return "inconclusive", "an evaluation run has conflicting human feedback"
        if reviewed_runs != len(evidence):
            return "inconclusive", "human feedback is missing for one or more evaluation runs"
        if machine_passed != len(evidence):
            return "inconclusive", "one or more machine gates did not pass"

        reviews = [
            review
            for item in evidence
            for feedback in feedback_by_evidence[item.evidence_id]
            for review in feedback.reviews
        ]
        if any(
            review.attribution == "factuality" and review.preference == "baseline"
            for review in reviews
        ):
            return "rejected", "human review found a Variant factuality regression"

        run_winners = [
            _winner(feedback_by_evidence[item.evidence_id][0].reviews) for item in evidence
        ]
        variant_runs = run_winners.count("variant")
        baseline_runs = run_winners.count("baseline")
        majority = len(evidence) // 2 + 1
        if variant_runs >= majority and counts["variant"] > counts["baseline"]:
            return "accepted", "Variant won a majority of comparable reviewed runs"
        if baseline_runs >= majority and counts["baseline"] > counts["variant"]:
            return "rejected", "Baseline won a majority of comparable reviewed runs"
        return "inconclusive", "human preferences do not establish a stable majority"


def _winner(reviews) -> str:
    counts = {"baseline": 0, "variant": 0}
    for review in reviews:
        if review.preference in counts:
            counts[review.preference] += 1
    if counts["variant"] > counts["baseline"]:
        return "variant"
    if counts["baseline"] > counts["variant"]:
        return "baseline"
    return "tie"
