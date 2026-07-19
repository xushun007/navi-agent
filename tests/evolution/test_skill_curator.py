from pathlib import Path

from navi_agent.evolution import (
    EvolutionCandidate,
    FileSkillStore,
    SkillCuratorStatusService,
    SkillCuratorService,
    SkillProvenanceStore,
    SkillUsageService,
    SkillUsageStore,
)
from navi_agent.telemetry import InMemoryTraceStore, RuntimeTrace


def test_curator_status_separates_agent_and_manual_skills(tmp_path: Path) -> None:
    skill_store = FileSkillStore(tmp_path)
    skill_store.create(name="agent-skill", content="description: Agent skill")
    skill_store.create(name="manual-skill", content="description: Manual skill")
    provenance_store = SkillProvenanceStore(tmp_path)
    provenance_store.mark_agent_created(
        skill_name="agent-skill",
        candidate=EvolutionCandidate(target="skill", summary="s", rationale="r"),
    )
    trace_store = InMemoryTraceStore()
    trace_store.record(
        RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="ok",
            status="success",
            injected_skill_names=["manual-skill"],
        )
    )

    status = SkillCuratorStatusService(
        usage_service=SkillUsageService(skill_store=skill_store, trace_store=trace_store),
        provenance_store=provenance_store,
    ).summarize()

    assert status.skill_count == 2
    assert status.agent_created_count == 1
    assert status.manual_count == 1
    assert status.unused_agent_created_count == 1
    by_name = {record.name: record for record in status.records}
    assert by_name["agent-skill"].origin == "agent"
    assert by_name["agent-skill"].candidate_action == "review-unused"
    assert by_name["manual-skill"].origin == "manual"
    assert by_name["manual-skill"].candidate_action == "ignore"


def test_curator_archives_unused_agent_created_skills(tmp_path: Path) -> None:
    skill_store = FileSkillStore(tmp_path)
    skill_store.create(name="unused-agent-skill", content="description: Unused")
    skill_store.create(name="used-agent-skill", content="description: Used")
    skill_store.create(name="manual-skill", content="description: Manual")
    provenance_store = SkillProvenanceStore(tmp_path)
    provenance_store.mark_agent_created(
        skill_name="unused-agent-skill",
        candidate=EvolutionCandidate(target="skill", summary="s", rationale="r"),
    )
    provenance_store.mark_agent_created(
        skill_name="used-agent-skill",
        candidate=EvolutionCandidate(target="skill", summary="s", rationale="r"),
    )
    trace_store = InMemoryTraceStore()
    trace_store.record(
        RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="ok",
            status="success",
            injected_skill_names=["used-agent-skill"],
        )
    )
    usage_store = SkillUsageStore(tmp_path)

    result = SkillCuratorService(
        skill_store=skill_store,
        usage_service=SkillUsageService(
            skill_store=skill_store,
            trace_store=trace_store,
            usage_store=usage_store,
        ),
        provenance_store=provenance_store,
        usage_store=usage_store,
    ).archive_unused_agent_created()

    assert result.archived_count == 1
    assert result.archived_names == ["unused-agent-skill"]
    assert (tmp_path / ".archive" / "unused-agent-skill" / "SKILL.md").exists()
    assert skill_store.get("used-agent-skill") is not None
    assert skill_store.get("manual-skill") is not None
    assert usage_store.get("unused-agent-skill").archived_count == 1
