from __future__ import annotations

from typing import Protocol

from .models import EvolutionCandidate


class CandidateStore(Protocol):
    def add(self, candidate: EvolutionCandidate) -> None: ...
