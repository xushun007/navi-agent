from __future__ import annotations

from .models import EvolutionCandidate, WorkflowEvolutionSample


class InMemoryCandidateStore:
    def __init__(self) -> None:
        self.candidates: list[EvolutionCandidate] = []

    def add(self, candidate: EvolutionCandidate) -> None:
        self.candidates.append(candidate)


class InMemoryWorkflowSampleStore:
    def __init__(self) -> None:
        self.samples: list[WorkflowEvolutionSample] = []

    def add(self, sample: WorkflowEvolutionSample) -> None:
        self.samples.append(sample)
