from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvaluationResult:
    session_id: str
    score: float
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvolutionCandidate:
    target: str
    summary: str
    rationale: str
    metadata: dict[str, Any] = field(default_factory=dict)
