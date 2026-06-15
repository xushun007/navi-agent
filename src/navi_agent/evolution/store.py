from __future__ import annotations

from typing import Protocol

from .models import EvolutionCandidate, WorkflowEvolutionSample


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


class WorkflowSampleStore(Protocol):
    def add(self, sample: WorkflowEvolutionSample) -> None: ...
    def list_recent(self, limit: int | None = None) -> list[WorkflowEvolutionSample]: ...
