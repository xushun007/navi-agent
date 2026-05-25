from __future__ import annotations

from navi_agent.telemetry import RuntimeTrace

from .models import EvaluationResult, EvolutionCandidate
from .store import CandidateStore


class SimpleEvaluator:
    def evaluate(self, trace: RuntimeTrace) -> EvaluationResult:
        score = 1.0 if trace.status == "success" else 0.0
        summary = "Successful run" if trace.status == "success" else "Failed run"
        return EvaluationResult(
            session_id=trace.session_id,
            score=score,
            summary=summary,
            metadata={"tool_names": list(trace.tool_names)},
        )

    def build_candidate(self, evaluation: EvaluationResult) -> EvolutionCandidate | None:
        if evaluation.score >= 1.0:
            return None
        return EvolutionCandidate(
            target="prompt",
            summary="Review failed runtime session",
            rationale=evaluation.summary,
            metadata={"session_id": evaluation.session_id},
        )

    def store_candidate(
        self,
        candidate_store: CandidateStore,
        candidate: EvolutionCandidate | None,
    ) -> None:
        if candidate is None:
            return
        candidate_store.add(candidate)
