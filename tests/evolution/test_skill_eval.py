from pathlib import Path

from navi_agent.evolution import (
    DefaultSkillAdmissionValidator,
    EvolutionReportWriter,
    FileSkillStore,
    SkillDraftProvenance,
    SkillEvalCase,
    SkillEvalRun,
    SkillEvalWorkflowService,
    SkillGovernanceService,
    SkillPromotionGate,
)
from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import RuntimeTrace


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


def test_evaluates_admitted_draft_without_activating_it(tmp_path: Path) -> None:
    active_store = FileSkillStore(tmp_path / "skills")
    governance = SkillGovernanceService(
        active_store,
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    )
    draft = governance.create_draft(
        skill_name="readme-review",
        content=_skill_content("- Include the verified marker."),
        provenance=SkillDraftProvenance(source_kind="human"),
    )
    draft = governance.admit(draft.draft_id, validator=DefaultSkillAdmissionValidator())
    observed_conditions: list[tuple[str, bool]] = []

    def run_case(case, skill_store, condition):
        has_candidate = skill_store.get("readme-review") is not None
        observed_conditions.append((condition, has_candidate))
        output = "verified marker" if has_candidate else "baseline output"
        session_id = f"{case.id}:{condition}"
        return SkillEvalRun(
            task_name=case.id,
            runtime_result=RuntimeResult(
                session_id=session_id,
                status="success",
                final_response=output,
            ),
            trace=RuntimeTrace(
                session_id=session_id,
                user_id="eval",
                user_message=case.prompt,
                final_response=output,
                status="success",
                trace_id=f"trace:{session_id}",
            ),
        )

    summary = SkillEvalWorkflowService(
        skill_store=active_store,
        governance=governance,
        runner=run_case,
        report_writer=EvolutionReportWriter(tmp_path / "reports"),
    ).evaluate(
        draft.draft_id,
        cases=[
            SkillEvalCase(
                id="readme-marker",
                prompt="Review the README",
                required_output_terms=("verified",),
            )
        ],
    )

    assert observed_conditions == [("baseline", False), ("variant", True)]
    assert summary.evaluation_result.suite == "skill_ab"
    assert summary.evaluation_result.passed is True
    assert summary.comparison.score_delta == 1.0
    assert active_store.get("readme-review") is None
    assert (summary.report_path / "run.json").exists()
    assert (summary.report_path / "REPORT.md").exists()
    assert (summary.report_path / "REVIEW.html").exists()


def test_rejects_unadmitted_draft_and_empty_case_set(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path / "skills")
    governance = SkillGovernanceService(
        store,
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    )
    draft = governance.create_draft(
        skill_name="readme-review",
        content=_skill_content("- Read README."),
        provenance=SkillDraftProvenance(source_kind="human"),
    )
    service = SkillEvalWorkflowService(
        skill_store=store,
        governance=governance,
        runner=lambda case, skill_store, condition: None,
        report_writer=EvolutionReportWriter(tmp_path / "reports"),
    )

    try:
        service.evaluate(draft.draft_id, cases=[])
    except ValueError as error:
        assert "not admitted" in str(error)
    else:
        raise AssertionError("unadmitted draft was evaluated")

    governance.admit(draft.draft_id, validator=DefaultSkillAdmissionValidator())
    try:
        service.evaluate(draft.draft_id, cases=[])
    except ValueError as error:
        assert "at least one case" in str(error)
    else:
        raise AssertionError("empty case set was evaluated")
