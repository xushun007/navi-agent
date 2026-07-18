from pathlib import Path

from navi_agent.evolution import (
    EvolutionCandidate,
    FileSkillStore,
    SkillCuratorStatusService,
    SkillProvenanceStore,
    SkillUsageService,
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
