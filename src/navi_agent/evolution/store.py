from __future__ import annotations

from typing import Protocol

from .models import EvolutionCandidate, WorkflowEvolutionSample


class CandidateStore(Protocol):
    def add(self, candidate: EvolutionCandidate) -> None: ...


class WorkflowSampleStore(Protocol):
    def add(self, sample: WorkflowEvolutionSample) -> None: ...
