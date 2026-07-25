from pathlib import Path

from navi_agent.evolution import (
    FileSkillStore,
    SkillDraftProvenance,
    SkillEvaluationResult,
    SkillGovernanceService,
    SkillPromotionGate,
)


class _Evaluator:
    def __init__(self, *results: SkillEvaluationResult) -> None:
        self._results = list(results)

    def evaluate(self, draft, proposed, active):
        return self._results


def _provenance() -> SkillDraftProvenance:
    return SkillDraftProvenance(
        review_run_id="review-1",
        source_session_id="session-1",
        source_trace_id="trace-1",
        evidence_ids=("message-1", "tool-1"),
    )


def _service(root: Path) -> tuple[FileSkillStore, SkillGovernanceService]:
    store = FileSkillStore(root)
    service = SkillGovernanceService(
        store,
        gate=SkillPromotionGate(required_suites=("targeted", "regression")),
    )
    return store, service


def _skill_content(procedure: str) -> str:
    return (
        "---\n"
        "name: readme-review\n"
        "description: Review README files.\n"
        "category: coding\n"
        "---\n\n"
        "# README Review\n\n"
        "## When To Use\n\nUse for README review.\n\n"
        f"## Procedure\n\n{procedure}\n"
    )


def _passing_evaluator() -> _Evaluator:
    return _Evaluator(
        SkillEvaluationResult("targeted", True, 0.5, 0.8),
        SkillEvaluationResult("regression", True, 1.0, 1.0),
    )


def test_draft_is_isolated_until_configured_gate_passes(tmp_path: Path) -> None:
    store, service = _service(tmp_path)

    draft = service.create_draft(
        skill_name="readme-review",
        content=_skill_content("- Read the file."),
        provenance=_provenance(),
    )

    assert store.get("readme-review") is None
    assert draft.status == "draft"
    assert draft.provenance.review_run_id == "review-1"

    promoted = service.evaluate_and_promote(
        draft.draft_id,
        evaluator=_passing_evaluator(),
    )

    assert promoted.status == "promoted"
    assert store.get("readme-review") is not None
    assert service.get_draft(draft.draft_id).active_version_id == draft.draft_id


def test_missing_or_failed_evaluation_preserves_active_skill(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    original = _skill_content("- Keep the active procedure.")
    store.create(name="readme-review", content=original)
    draft = service.append_draft(
        skill_name="readme-review",
        section="## Procedure",
        content="- Proposed change.",
        provenance=_provenance(),
    )

    decided = service.evaluate_and_promote(
        draft.draft_id,
        evaluator=_Evaluator(SkillEvaluationResult("targeted", True, 0.5, 0.8)),
    )

    assert decided.status == "rejected"
    assert "missing required" in decided.decision_reason
    assert store.get("readme-review").content == original


def test_records_no_improvement_and_regression_without_activation(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    original = _skill_content("- Keep the active procedure.")
    store.create(name="readme-review", content=original)

    unchanged = service.append_draft(
        skill_name="readme-review",
        section="## Procedure",
        content="- Equivalent step.",
        provenance=_provenance(),
    )
    unchanged = service.evaluate_and_promote(
        unchanged.draft_id,
        evaluator=_Evaluator(
            SkillEvaluationResult("targeted", True, 0.8, 0.8),
            SkillEvaluationResult("regression", True, 1.0, 1.0),
        ),
    )
    regressed = service.append_draft(
        skill_name="readme-review",
        section="## Procedure",
        content="- Risky step.",
        provenance=_provenance(),
    )
    regressed = service.evaluate_and_promote(
        regressed.draft_id,
        evaluator=_Evaluator(
            SkillEvaluationResult("targeted", True, 0.8, 0.9),
            SkillEvaluationResult("regression", False, 1.0, 0.7, "regression failed"),
        ),
    )

    assert unchanged.status == "no_improvement"
    assert regressed.status == "regressed"
    assert store.get("readme-review").content == original


def test_promoted_skill_can_rollback_with_attachments(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    original = _skill_content("- Keep the original procedure.")
    store.create(name="readme-review", content=original)
    store.write_attachment(
        name="readme-review",
        relative_path="templates/report.md",
        content="original",
    )
    draft = service.append_draft(
        skill_name="readme-review",
        section="## Procedure",
        content="- Add a verified step.",
        provenance=_provenance(),
    )
    service.write_draft_attachment(
        draft_id=draft.draft_id,
        relative_path="templates/report.md",
        content="proposed",
    )
    promoted = service.evaluate_and_promote(
        draft.draft_id,
        evaluator=_passing_evaluator(),
    )

    assert promoted.previous_version_id.startswith("baseline-")
    assert store.read_attachment(
        name="readme-review",
        relative_path="templates/report.md",
    ) == "proposed"

    rolled_back = service.rollback("readme-review")

    assert rolled_back.status == "rolled_back"
    assert store.get("readme-review").content == original
    assert store.read_attachment(
        name="readme-review",
        relative_path="templates/report.md",
    ) == "original"


def test_evaluator_exception_is_audited_as_rejection(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    draft = service.create_draft(
        skill_name="readme-review",
        content=_skill_content("- Read the file."),
        provenance=_provenance(),
    )

    class _BrokenEvaluator:
        def evaluate(self, draft, proposed, active):
            raise RuntimeError("suite unavailable")

    rejected = service.evaluate_and_promote(
        draft.draft_id,
        evaluator=_BrokenEvaluator(),
    )

    assert rejected.status == "rejected"
    assert rejected.decision_reason == "evaluation failed: suite unavailable"
