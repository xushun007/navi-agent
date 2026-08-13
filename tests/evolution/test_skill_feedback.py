import json
from pathlib import Path

import pytest

from navi_agent.evolution import (
    DefaultSkillAdmissionValidator,
    FileSkillStore,
    SkillEvaluationResult,
    SkillFeedbackImportService,
    SkillDraftProvenance,
    SkillGovernanceService,
    SkillPromotionGate,
)


def _setup(tmp_path: Path):
    store = FileSkillStore(tmp_path / "skills")
    governance = SkillGovernanceService(
        store,
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
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    report = {
        "workflow_name": "skill:internal-comms",
        "source_session_id": f"{draft.draft_id}:baseline",
        "replay_session_id": f"{draft.draft_id}:variant",
        "eval_case": {
            "metadata": {
                "draft_id": draft.draft_id,
                "skill_name": "internal-comms",
                "case_fingerprint": "sha256:cases",
            }
        },
        "step_comparisons": [
            {"task_name": "weekly-update"},
            {"task_name": "leadership-update"},
        ],
    }
    (report_dir / "run.json").write_text(json.dumps(report), encoding="utf-8")
    recorded = governance.record_evaluation(
        draft.draft_id,
        evaluation_results=[SkillEvaluationResult("skill_ab", True, 0.5, 1.0)],
        case_fingerprint="sha256:cases",
        report_path=str(report_dir),
        source_session_id=report["source_session_id"],
        replay_session_id=report["replay_session_id"],
    )
    return governance, recorded, report_dir


def _write_feedback(path: Path, *, workflow: str = "skill:internal-comms") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workflow_name": workflow,
                "exported_at": "2026-08-13T10:00:00Z",
                "reviews": [
                    {
                        "task_name": "weekly-update",
                        "preference": "variant",
                        "attribution": "",
                        "notes": "More concise.",
                    },
                    {
                        "task_name": "leadership-update",
                        "preference": "tie",
                        "attribution": "instruction_quality",
                        "notes": "Similar quality.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_imports_feedback_and_is_idempotent(tmp_path: Path) -> None:
    governance, draft, report_dir = _setup(tmp_path)
    feedback_path = tmp_path / "feedback.json"
    _write_feedback(feedback_path)
    service = SkillFeedbackImportService(governance)

    first = service.import_feedback(
        draft.draft_id,
        report_path=report_dir,
        feedback_path=feedback_path,
    )
    second = service.import_feedback(
        draft.draft_id,
        report_path=report_dir / "run.json",
        feedback_path=feedback_path,
    )

    assert first.feedback.feedback_id == second.feedback.feedback_id
    assert first.preference_counts == {"baseline": 0, "tie": 1, "variant": 1}
    assert first.feedback.evidence_id == draft.evaluation_evidence_ids[0]
    assert first.feedback.report_hash.startswith("sha256:")
    assert first.feedback.feedback_hash.startswith("sha256:")
    assert len(governance.list_human_feedback(draft.draft_id)) == 1
    persisted = governance.get_draft(draft.draft_id)
    assert persisted is not None
    assert persisted.status == "candidate"
    assert persisted.human_feedback_ids == [first.feedback.feedback_id]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update(workflow_name="skill:other"), "workflow"),
        (lambda payload: payload.update(schema_version=2), "schema_version"),
        (lambda payload: payload["reviews"].pop(), "task names"),
        (
            lambda payload: payload["reviews"][0].update(preference=""),
            "requires preference",
        ),
    ],
)
def test_rejects_feedback_that_does_not_match_report(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    governance, draft, report_dir = _setup(tmp_path)
    feedback_path = tmp_path / "feedback.json"
    _write_feedback(feedback_path)
    payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    mutation(payload)
    feedback_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        SkillFeedbackImportService(governance).import_feedback(
            draft.draft_id,
            report_path=report_dir,
            feedback_path=feedback_path,
        )
