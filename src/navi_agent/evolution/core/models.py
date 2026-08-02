from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class EvaluationResult:
    session_id: str
    score: float
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvolutionGateResult:
    workflow_name: str
    case_fingerprint: str
    baseline_session_id: str
    candidate_session_id: str
    baseline_score: float
    candidate_score: float
    score_delta: float
    status: str
    report_path: str
    evaluated_at: str


@dataclass(slots=True)
class EvolutionRollback:
    reason: str
    rolled_back_at: str
    previous_status: str = "applied"


@dataclass(slots=True)
class EvolutionCandidate:
    target: str
    summary: str
    rationale: str
    candidate_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "pending"
    reviewed_at: str | None = None
    review_note: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    expected_outcome: str = ""
    source_trace_id: str | None = None
    gate_result: EvolutionGateResult | None = None
    rollback: EvolutionRollback | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalCase:
    workflow_name: str
    source_session_id: str
    replay_session_id: str
    source_average_score: float
    replay_average_score: float
    score_delta: float
    status: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
