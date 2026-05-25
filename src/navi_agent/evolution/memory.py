from __future__ import annotations

from .models import EvolutionCandidate


class InMemoryCandidateStore:
    def __init__(self) -> None:
        self.candidates: list[EvolutionCandidate] = []

    def add(self, candidate: EvolutionCandidate) -> None:
        self.candidates.append(candidate)
