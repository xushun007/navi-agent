import json
from pathlib import Path

import pytest

from navi_agent.cli.skill import (
    activate_skill_draft,
    load_skill_eval_cases,
    stage_skill_directory,
)
from navi_agent.evolution import (
    FileSkillStore,
    SkillEvaluationResult,
    SkillGovernanceService,
    SkillHumanReview,
    SkillPromotionGate,
)


def test_loads_minimal_skill_eval_case_file(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "readme-review",
                        "prompt": "Review README.md",
                        "required_output_terms": ["verified"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = load_skill_eval_cases(path)

    assert cases[0].id == "readme-review"
    assert cases[0].required_output_terms == ("verified",)


def test_rejects_empty_skill_eval_case_file(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text('{"cases": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty cases"):
        load_skill_eval_cases(path)


def test_imports_bundled_skill_as_inactive_candidate(tmp_path: Path, monkeypatch) -> None:
    active_root = tmp_path / "active"
    source = tmp_path / "external-review"
    (source / "references").mkdir(parents=True)
    (source / "assets").mkdir()
    (source / "SKILL.md").write_text(
        "---\n"
        "name: external-review\n"
        "description: Review external documents.\n"
        "category: review\n"
        "---\n\n"
        "# External Review\n\n"
        "## When To Use\n\nUse for external reviews.\n\n"
        "## Procedure\n\n- Read the reference.\n",
        encoding="utf-8",
    )
    (source / "references" / "policy.md").write_text("policy", encoding="utf-8")
    (source / "assets" / "template.bin").write_bytes(b"template")
    monkeypatch.setattr("navi_agent.cli.skill.get_skills_dir", lambda: active_root)

    draft_id = stage_skill_directory(source, source_kind="external")

    governance = SkillGovernanceService(
        FileSkillStore(active_root),
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    )
    draft = governance.get_draft(draft_id)
    draft_skill = governance.get_draft_skill(draft_id)
    assert draft is not None
    assert draft.status == "candidate"
    assert draft.provenance.source_kind == "external"
    assert FileSkillStore(active_root).get("external-review") is None
    assert draft_skill is not None
    assert {item.path for item in draft_skill.attachments} == {
        "assets/template.bin",
        "references/policy.md",
    }


def test_imports_standard_skill_without_navi_specific_sections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    active_root = tmp_path / "active"
    source = tmp_path / "standard-review"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\n"
        "name: standard-review\n"
        "description: Review documents against a concise checklist.\n"
        "---\n\n"
        "# Standard Review\n\n"
        "Check the document, cite evidence, and report uncertainty.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("navi_agent.cli.skill.get_skills_dir", lambda: active_root)

    draft_id = stage_skill_directory(source, source_kind="external")

    governance = SkillGovernanceService(
        FileSkillStore(active_root),
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    )
    draft = governance.get_draft(draft_id)
    assert draft is not None
    assert draft.status == "candidate"


def test_activation_requires_accepted_evaluation_aggregate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    active_root = tmp_path / "active"
    source = tmp_path / "human-review"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\n"
        "name: human-review\n"
        "description: Review human-authored documents.\n"
        "category: review\n"
        "---\n\n"
        "# Human Review\n\n"
        "## When To Use\n\nUse for human reviews.\n\n"
        "## Procedure\n\n- Verify the document.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("navi_agent.cli.skill.get_skills_dir", lambda: active_root)
    draft_id = stage_skill_directory(source, source_kind="human")

    with pytest.raises(ValueError, match="inconclusive.*at least 3"):
        activate_skill_draft(draft_id)

    governance = SkillGovernanceService(
        FileSkillStore(active_root),
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    )
    for index, preferences in enumerate(
        (
            ("variant", "variant"),
            ("variant", "tie"),
            ("tie", "baseline"),
        ),
        start=1,
    ):
        evaluated = governance.record_evaluation(
            draft_id,
            evaluation_results=[SkillEvaluationResult("skill_ab", True, 1.0, 1.0)],
            case_fingerprint="sha256:cases",
            model_config_fingerprint="sha256:model",
            report_path=f"/tmp/report-{index}",
        )
        governance.record_human_feedback(
            draft_id,
            evidence_id=evaluated.evaluation_evidence_ids[-1],
            schema_version=1,
            workflow_name="skill:human-review",
            exported_at=f"2026-08-17T10:00:0{index}Z",
            report_hash=f"sha256:report-{index}",
            feedback_hash=f"sha256:feedback-{index}",
            source_path=f"/tmp/feedback-{index}.json",
            reviews=tuple(
                SkillHumanReview(f"case-{case_index}", preference)
                for case_index, preference in enumerate(preferences)
            ),
        )

    assert activate_skill_draft(draft_id) == "promoted"
    assert FileSkillStore(active_root).get("human-review") is not None


def test_failed_activation_keeps_skill_candidate(tmp_path: Path, monkeypatch) -> None:
    active_root = tmp_path / "active"
    source = tmp_path / "human-review"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\n"
        "name: human-review\n"
        "description: Review human-authored documents.\n"
        "---\n\n"
        "# Human Review\n\nVerify the document.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("navi_agent.cli.skill.get_skills_dir", lambda: active_root)
    draft_id = stage_skill_directory(source, source_kind="human")

    with pytest.raises(ValueError, match="inconclusive"):
        activate_skill_draft(draft_id)

    draft = SkillGovernanceService(
        FileSkillStore(active_root),
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    ).get_draft(draft_id)
    assert draft is not None
    assert draft.status == "candidate"
