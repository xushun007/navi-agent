from __future__ import annotations

from .models import EvolutionCandidate, EvalCase


class InMemoryCandidateStore:
    def __init__(self) -> None:
        self.candidates: list[EvolutionCandidate] = []

    def add(self, candidate: EvolutionCandidate) -> None:
        self.candidates.append(candidate)

    def list_recent(self, limit: int | None = None) -> list[EvolutionCandidate]:
        items = list(reversed(self.candidates))
        if limit is None:
            return items
        return items[:limit]

    def get(self, candidate_id: str) -> EvolutionCandidate | None:
        for candidate in self.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def update_status(
        self,
        candidate_id: str,
        status: str,
        *,
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        candidate = self.get(candidate_id)
        if candidate is None:
            return None
        candidate.status = status
        candidate.review_note = review_note
        return candidate


class InMemoryEvalCaseStore:
    def __init__(self) -> None:
        self.eval_cases: list[EvalCase] = []

    def add(self, eval_case: EvalCase) -> None:
        self.eval_cases.append(eval_case)

    def list_recent(self, limit: int | None = None) -> list[EvalCase]:
        items = list(reversed(self.eval_cases))
        if limit is None:
            return items
        return items[:limit]
