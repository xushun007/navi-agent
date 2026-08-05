from __future__ import annotations

from datetime import datetime, timezone
from math import isclose, isfinite

from .models import EvalCase, EvolutionGateResult


class EvolutionGate:
    """Build a reproducible baseline-versus-candidate promotion decision."""

    def __init__(self, *, minimum_improvement: float = 0.01) -> None:
        if minimum_improvement < 0:
            raise ValueError("minimum_improvement must not be negative")
        self._minimum_improvement = minimum_improvement

    def evaluate(self, eval_case: EvalCase, *, report_path: str) -> EvolutionGateResult:
        fingerprint = str(eval_case.metadata.get("case_fingerprint") or "").strip()
        if not fingerprint:
            raise ValueError("eval case must include a case_fingerprint")
        if not eval_case.source_session_id or not eval_case.replay_session_id:
            raise ValueError("eval case must identify baseline and candidate sessions")
        correctness_passed = eval_case.metadata.get("correctness_passed")
        if not isinstance(correctness_passed, bool):
            raise ValueError("eval case must include boolean correctness_passed evidence")
        scores = (
            eval_case.source_average_score,
            eval_case.replay_average_score,
            eval_case.score_delta,
        )
        if not all(isfinite(score) for score in scores):
            raise ValueError("eval case scores must be finite")
        calculated_delta = round(
            eval_case.replay_average_score - eval_case.source_average_score,
            3,
        )
        if not isclose(eval_case.score_delta, calculated_delta, abs_tol=0.001):
            raise ValueError("eval case score_delta does not match its scores")

        if not correctness_passed:
            status = "regressed_after_apply"
        elif calculated_delta > self._minimum_improvement:
            status = "verified"
        elif calculated_delta < -self._minimum_improvement:
            status = "regressed_after_apply"
        else:
            status = "no_improvement"

        return EvolutionGateResult(
            workflow_name=eval_case.workflow_name,
            case_fingerprint=fingerprint,
            baseline_session_id=eval_case.source_session_id,
            candidate_session_id=eval_case.replay_session_id,
            baseline_score=eval_case.source_average_score,
            candidate_score=eval_case.replay_average_score,
            score_delta=calculated_delta,
            status=status,
            report_path=report_path,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )
