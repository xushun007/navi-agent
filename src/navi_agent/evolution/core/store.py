from __future__ import annotations

from typing import Protocol

from .models import EvolutionCandidate, EvalCase


class CandidateStore(Protocol):
    def add(self, candidate: EvolutionCandidate) -> None: ...
    def list_recent(self, limit: int | None = None) -> list[EvolutionCandidate]: ...
    def get(self, candidate_id: str) -> EvolutionCandidate | None: ...
    def update_status(
        self,
        candidate_id: str,
        status: str,
        *,
        review_note: str | None = None,
    ) -> EvolutionCandidate | None: ...


class EvalCaseStore(Protocol):
    def add(self, eval_case: EvalCase) -> None: ...
    def list_recent(self, limit: int | None = None) -> list[EvalCase]: ...
