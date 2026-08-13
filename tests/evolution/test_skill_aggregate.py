from pathlib import Path

from navi_agent.evolution import (
    DefaultSkillAdmissionValidator,
    FileSkillStore,
    SkillDraftProvenance,
    SkillEvaluationAggregateService,
    SkillEvaluationResult,
    SkillGovernanceService,
    SkillHumanReview,
    SkillPromotionGate,
)


def _service(tmp_path: Path):
    governance = SkillGovernanceService(
        FileSkillStore(tmp_path / "skills"),
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    )
    draft = governance.create_draft(
        skill_name="internal-comms",
        content=(
            "---\nname: internal-comms\ndescription: Write internal updates.\n---\n\n"
            "# Internal Comms\n\nUse concise formats.\n"
        ),
        provenance=SkillDraftProvenance(source_kind="human"),
    )
    governance.admit(draft.draft_id, validator=DefaultSkillAdmissionValidator())
    return governance, draft.draft_id


def _record_run(governance, draft_id: str, index: int, preferences, *, passed=True):
    draft = governance.record_evaluation(
        draft_id,
        evaluation_results=[SkillEvaluationResult("skill_ab", passed, 0.5, 1.0)],
        case_fingerprint="sha256:cases",
        model_config_fingerprint="sha256:model",
        report_path=f"/tmp/report-{index}",
    )
    evidence_id = draft.evaluation_evidence_ids[-1]
    governance.record_human_feedback(
        draft_id,
        evidence_id=evidence_id,
        schema_version=1,
        workflow_name="skill:internal-comms",
        exported_at=f"2026-08-13T10:00:0{index}Z",
        report_hash=f"sha256:report-{index}",
        feedback_hash=f"sha256:feedback-{index}",
        source_path=f"/tmp/feedback-{index}.json",
        reviews=tuple(
            SkillHumanReview(f"case-{case_index}", preference, attribution)
            for case_index, (preference, attribution) in enumerate(preferences)
        ),
    )


def test_accepts_variant_with_machine_passes_and_reviewed_run_majority(tmp_path: Path) -> None:
    governance, draft_id = _service(tmp_path)
    _record_run(governance, draft_id, 1, [("variant", ""), ("variant", "")])
    _record_run(governance, draft_id, 2, [("variant", ""), ("tie", "")])
    _record_run(governance, draft_id, 3, [("tie", ""), ("baseline", "")])

    result = SkillEvaluationAggregateService(governance).aggregate(draft_id)

    assert result.status == "accepted"
    assert result.run_count == 3
    assert result.reviewed_run_count == 3
    assert result.machine_passed_run_count == 3
    assert result.preference_counts == {"baseline": 1, "tie": 2, "variant": 3}


def test_rejects_variant_factuality_regression(tmp_path: Path) -> None:
    governance, draft_id = _service(tmp_path)
    _record_run(governance, draft_id, 1, [("variant", "")])
    _record_run(governance, draft_id, 2, [("variant", "")])
    _record_run(governance, draft_id, 3, [("baseline", "factuality")])

    result = SkillEvaluationAggregateService(governance).aggregate(draft_id)

    assert result.status == "rejected"
    assert "factuality" in result.reason


def test_is_inconclusive_when_runs_or_feedback_are_missing(tmp_path: Path) -> None:
    governance, draft_id = _service(tmp_path)
    _record_run(governance, draft_id, 1, [("variant", "")])
    _record_run(governance, draft_id, 2, [("variant", "")])

    too_few = SkillEvaluationAggregateService(governance).aggregate(draft_id)

    assert too_few.status == "inconclusive"
    assert "at least 3" in too_few.reason

    governance.record_evaluation(
        draft_id,
        evaluation_results=[SkillEvaluationResult("skill_ab", True, 0.5, 1.0)],
        case_fingerprint="sha256:cases",
        model_config_fingerprint="sha256:model",
        report_path="/tmp/report-3",
    )
    missing_review = SkillEvaluationAggregateService(governance).aggregate(draft_id)

    assert missing_review.status == "inconclusive"
    assert "feedback is missing" in missing_review.reason
