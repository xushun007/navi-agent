from pathlib import Path

from navi_agent.evolution import (
    FileSkillStore,
    DefaultSkillAdmissionValidator,
    SkillDraftProvenance,
    SkillEvaluationResult,
    SkillGovernanceService,
    SkillPromotionGate,
)


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


def _passing_results() -> list[SkillEvaluationResult]:
    return [
        SkillEvaluationResult("targeted", True, 0.5, 0.8),
        SkillEvaluationResult("regression", True, 1.0, 1.0),
    ]


def _admit(service: SkillGovernanceService, draft_id: str):
    return service.admit(draft_id, validator=DefaultSkillAdmissionValidator())


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

    admitted = _admit(service, draft.draft_id)

    assert admitted.status == "candidate"
    assert store.get("readme-review") is None

    promoted = service.activate(draft.draft_id, evaluation_results=_passing_results())

    assert promoted.status == "promoted"
    assert store.get("readme-review") is not None
    assert service.get_draft(draft.draft_id).active_version_id == draft.draft_id
    version = service.get_version("readme-review", draft.draft_id)
    assert version is not None
    assert version.status == "active"
    assert version.parent_version_id == ""
    assert version.provenance == _provenance()
    assert len(version.content_hash) == 64
    assert [result.suite for result in version.evaluation_results] == [
        "targeted",
        "regression",
    ]
    change_diff = (
        tmp_path
        / ".governance"
        / "versions"
        / "readme-review"
        / draft.draft_id
        / version.diff_path
    ).read_text(encoding="utf-8")
    assert "--- /dev/null" in change_diff
    assert "+++ b/SKILL.md" in change_diff


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

    _admit(service, draft.draft_id)
    decided = service.activate(
        draft.draft_id,
        evaluation_results=[SkillEvaluationResult("targeted", True, 0.5, 0.8)],
    )

    assert decided.status == "rejected"
    assert "missing required" in decided.decision_reason
    assert decided.evaluation_results == [
        SkillEvaluationResult("targeted", True, 0.5, 0.8)
    ]
    assert store.get("readme-review").content == original


def test_evaluation_evidence_is_appended_without_losing_previous_runs(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    draft = service.create_draft(
        skill_name="readme-review",
        content=_skill_content("- Read the file."),
        provenance=_provenance(),
    )
    _admit(service, draft.draft_id)

    first = SkillEvaluationResult("targeted", True, 0.5, 0.8)
    service.record_evaluation(
        draft.draft_id,
        evaluation_results=[first],
        case_fingerprint="sha256:cases",
        model_config_fingerprint="sha256:model",
        report_path="/tmp/report-1",
        source_session_id="baseline-1",
        replay_session_id="variant-1",
        trace_ids=("trace-1", "trace-2"),
    )
    second = SkillEvaluationResult("targeted", True, 0.6, 0.9)
    recorded = service.record_evaluation(
        draft.draft_id,
        evaluation_results=[second],
        report_path="/tmp/report-2",
    )

    evidence = service.list_evaluation_evidence(draft.draft_id)
    assert len(evidence) == 2
    assert recorded.evaluation_results == [second]
    assert recorded.evaluation_evidence_ids == [item.evidence_id for item in evidence]
    assert evidence[0].evaluation_results == (first,)
    assert evidence[0].case_fingerprint == "sha256:cases"
    assert evidence[0].model_config_fingerprint == "sha256:model"
    assert evidence[0].report_path == "/tmp/report-1"
    assert evidence[0].trace_ids == ("trace-1", "trace-2")
    assert evidence[1].evaluation_results == (second,)
    assert len(evidence[0].skill_content_hash) == 64


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
    _admit(service, unchanged.draft_id)
    unchanged = service.activate(
        unchanged.draft_id,
        evaluation_results=[
            SkillEvaluationResult("targeted", True, 0.8, 0.8),
            SkillEvaluationResult("regression", True, 1.0, 1.0),
        ],
    )
    regressed = service.append_draft(
        skill_name="readme-review",
        section="## Procedure",
        content="- Risky step.",
        provenance=_provenance(),
    )
    _admit(service, regressed.draft_id)
    regressed = service.activate(
        regressed.draft_id,
        evaluation_results=[
            SkillEvaluationResult("targeted", True, 0.8, 0.9),
            SkillEvaluationResult("regression", False, 1.0, 0.7, "regression failed"),
        ],
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
    _admit(service, draft.draft_id)
    promoted = service.activate(draft.draft_id, evaluation_results=_passing_results())

    assert promoted.previous_version_id.startswith("baseline-")
    baseline = service.get_version("readme-review", promoted.previous_version_id)
    active = service.get_version("readme-review", promoted.draft_id)
    assert baseline is not None
    assert baseline.status == "deprecated"
    assert baseline.operation == "baseline"
    assert active is not None
    assert active.status == "active"
    assert active.parent_version_id == baseline.version_id
    change_diff = (
        tmp_path
        / ".governance"
        / "versions"
        / "readme-review"
        / promoted.draft_id
        / active.diff_path
    ).read_text(encoding="utf-8")
    assert "+- Add a verified step." in change_diff
    assert "-original" in change_diff
    assert "+proposed" in change_diff
    assert store.read_attachment(
        name="readme-review",
        relative_path="templates/report.md",
    ) == "proposed"

    rolled_back = service.rollback("readme-review")

    assert rolled_back.status == "rolled_back"
    assert service.get_version("readme-review", promoted.draft_id).status == "deprecated"
    assert service.get_version("readme-review", promoted.previous_version_id).status == "active"
    assert store.get("readme-review").content == original
    assert store.read_attachment(
        name="readme-review",
        relative_path="templates/report.md",
    ) == "original"


def test_admission_exception_is_audited_as_rejection(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    draft = service.create_draft(
        skill_name="readme-review",
        content=_skill_content("- Read the file."),
        provenance=_provenance(),
    )

    class _BrokenValidator:
        def validate(self, draft, proposed, active):
            raise RuntimeError("validator unavailable")

    rejected = service.admit(draft.draft_id, validator=_BrokenValidator())

    assert rejected.status == "rejected"
    assert rejected.decision_reason == "admission failed: validator unavailable"


def test_human_and_external_sources_can_enter_candidate_catalog(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    human = service.create_draft(
        skill_name="readme-review",
        content=_skill_content("- Read the file."),
        provenance=SkillDraftProvenance(source_kind="human"),
    )
    external = service.create_draft(
        skill_name="external-review",
        content=_skill_content("- Read the imported file.").replace(
            "name: readme-review", "name: external-review"
        ),
        provenance=SkillDraftProvenance(
            source_kind="external",
            source_uri="/tmp/external-review",
        ),
    )

    human = _admit(service, human.draft_id)
    external = _admit(service, external.draft_id)

    assert human.status == "candidate"
    assert human.provenance.source_kind == "human"
    assert external.status == "candidate"
    assert external.provenance.source_uri == "/tmp/external-review"
