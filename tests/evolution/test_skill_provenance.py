from pathlib import Path

from navi_agent.evolution import EvolutionCandidate, SkillProvenanceStore


def test_marks_agent_created_skill(tmp_path: Path) -> None:
    store = SkillProvenanceStore(tmp_path)
    candidate = EvolutionCandidate(
        target="skill",
        summary="Create skill",
        rationale="Reusable workflow",
        candidate_id="candidate-1",
        metadata={
            "source_session_id": "session-1",
            "source_trace_id": "trace-1",
            "reviewer": "llm",
        },
    )

    record = store.mark_agent_created(skill_name="readme-summary", candidate=candidate)

    assert record.name == "readme-summary"
    assert record.origin == "agent"
    assert record.source_candidate_id == "candidate-1"
    assert record.source_session_id == "session-1"
    assert record.source_trace_id == "trace-1"
    assert store.is_agent_created("readme-summary")
    assert (tmp_path / ".provenance.json").exists()


def test_returns_none_for_missing_or_invalid_sidecar(tmp_path: Path) -> None:
    store = SkillProvenanceStore(tmp_path)

    assert store.get("missing") is None
    assert not store.is_agent_created("missing")

    (tmp_path / ".provenance.json").write_text("not-json", encoding="utf-8")

    assert store.list() == []


def test_removes_provenance_record(tmp_path: Path) -> None:
    store = SkillProvenanceStore(tmp_path)
    candidate = EvolutionCandidate(target="skill", summary="s", rationale="r")
    store.mark_agent_created(skill_name="readme-summary", candidate=candidate)

    removed = store.remove("readme-summary")

    assert removed
    assert store.get("readme-summary") is None
    assert not store.is_agent_created("readme-summary")
