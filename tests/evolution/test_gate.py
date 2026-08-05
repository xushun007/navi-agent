from __future__ import annotations

import pytest

from navi_agent.evolution import EvalCase, EvolutionGate


def _eval_case(*, baseline: float = 0.7, candidate: float = 0.8) -> EvalCase:
    return EvalCase(
        workflow_name="agent-healthcheck",
        source_session_id="baseline-run",
        replay_session_id="candidate-run",
        source_average_score=baseline,
        replay_average_score=candidate,
        score_delta=round(candidate - baseline, 3),
        status="improved",
        summary="comparison",
        metadata={
            "case_fingerprint": "sha256:stable-cases",
            "correctness_passed": True,
        },
    )


def test_gate_verifies_a_measurable_improvement() -> None:
    result = EvolutionGate().evaluate(_eval_case(), report_path="reports/run-1")

    assert result.status == "verified"
    assert result.case_fingerprint == "sha256:stable-cases"
    assert result.baseline_session_id == "baseline-run"
    assert result.candidate_session_id == "candidate-run"
    assert result.score_delta == 0.1
    assert result.report_path == "reports/run-1"
    assert result.evaluated_at


@pytest.mark.parametrize(
    ("baseline", "candidate", "expected"),
    [
        (0.7, 0.7, "no_improvement"),
        (0.8, 0.7, "regressed_after_apply"),
    ],
)
def test_gate_blocks_changes_that_do_not_improve(
    baseline: float,
    candidate: float,
    expected: str,
) -> None:
    result = EvolutionGate().evaluate(
        _eval_case(baseline=baseline, candidate=candidate),
        report_path="reports/run-1",
    )

    assert result.status == expected


def test_gate_requires_a_reproducible_case_fingerprint() -> None:
    eval_case = _eval_case()
    eval_case.metadata.clear()

    with pytest.raises(ValueError, match="case_fingerprint"):
        EvolutionGate().evaluate(eval_case, report_path="reports/run-1")


def test_gate_requires_correctness_evidence() -> None:
    eval_case = _eval_case()
    del eval_case.metadata["correctness_passed"]

    with pytest.raises(ValueError, match="correctness_passed"):
        EvolutionGate().evaluate(eval_case, report_path="reports/run-1")


def test_gate_rejects_improvement_when_correctness_fails() -> None:
    eval_case = _eval_case()
    eval_case.metadata["correctness_passed"] = False

    result = EvolutionGate().evaluate(eval_case, report_path="reports/run-1")

    assert result.status == "regressed_after_apply"


def test_gate_rejects_an_inconsistent_score_delta() -> None:
    eval_case = _eval_case()
    eval_case.score_delta = -0.1

    with pytest.raises(ValueError, match="score_delta"):
        EvolutionGate().evaluate(eval_case, report_path="reports/run-1")
