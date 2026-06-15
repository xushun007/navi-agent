from __future__ import annotations

from typing import Protocol

from .models import EvolutionCandidate, WorkflowEvolutionSample


class CandidateStore(Protocol):
    def add(self, candidate: EvolutionCandidate) -> None: ...
    def list_recent(self, limit: int | None = None) -> list[EvolutionCandidate]: ...


class WorkflowSampleStore(Protocol):
    def add(self, sample: WorkflowEvolutionSample) -> None: ...
    def list_recent(self, limit: int | None = None) -> list[WorkflowEvolutionSample]: ...
