from pathlib import Path

from navi_agent.evolution import EvolutionEngine, FileSkillStore
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


def test_proposes_skill_candidate_from_successful_tool_trace() -> None:
    trace = _tool_trace()

    candidate = EvolutionEngine().propose_skill_candidate(trace)

    assert candidate is not None
    assert candidate.target == "skill"
    assert candidate.status == "pending"
    assert candidate.metadata["source_session_id"] == "session-1"
    assert candidate.metadata["source_trace_id"] == trace.trace_id
    assert candidate.metadata["skill_name"].startswith("learned-summarize-readme")
    assert candidate.metadata["tool_names"] == ["read_file", "bash"]
    assert "## When To Use" in candidate.metadata["skill_content"]
    assert "## Procedure" in candidate.metadata["skill_content"]


def test_does_not_propose_skill_for_failed_or_toolless_trace() -> None:
    engine = EvolutionEngine()
    failed_trace = _tool_trace(status="failed")
    toolless_trace = RuntimeTrace(
        session_id="session-2",
        user_id="user-1",
        user_message="What is Navi Agent?",
        final_response="Navi Agent is a personal assistant.",
        status="success",
    )

    assert engine.propose_skill_candidate(failed_trace) is None
    assert engine.propose_skill_candidate(toolless_trace) is None


def test_applies_accepted_skill_candidate_to_store(tmp_path: Path) -> None:
    engine = EvolutionEngine()
    candidate = engine.propose_skill_candidate(_tool_trace())
    assert candidate is not None
    candidate.status = "accepted"

    record = engine.apply_skill_candidate(
        candidate,
        skill_store=FileSkillStore(tmp_path),
    )

    assert record is not None
    assert record.path == tmp_path / candidate.metadata["skill_name"] / "SKILL.md"
    assert record.path.exists()
    assert "source_session_id: session-1" in record.content


def test_does_not_apply_pending_skill_candidate(tmp_path: Path) -> None:
    engine = EvolutionEngine()
    candidate = engine.propose_skill_candidate(_tool_trace())
    assert candidate is not None

    record = engine.apply_skill_candidate(
        candidate,
        skill_store=FileSkillStore(tmp_path),
    )

    assert record is None
    assert list(tmp_path.iterdir()) == []


def test_removes_skill_directory(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    record = store.create(name="readme-summary", content="# README Summary\n")

    removed = store.remove("readme-summary")

    assert removed
    assert not record.path.exists()
    assert store.get("readme-summary") is None


def test_search_returns_relevant_skills(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-summary",
        content="\n".join(
            [
                "---",
                "description: Summarize README files and run tests",
                "---",
                "Use read_file before bash.",
            ]
        ),
    )
    store.create(
        name="wechat-pairing",
        content="\n".join(
            [
                "---",
                "description: Handle Weixin pairing code flow",
                "---",
                "Use gateway traces.",
            ]
        ),
    )

    records = store.search("Please summarize README and test it")

    assert [record.name for record in records] == ["readme-summary"]


def test_search_limit_must_be_positive(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)

    try:
        store.search("readme", limit=0)
    except ValueError as error:
        assert str(error) == "limit must be positive"
    else:
        raise AssertionError("expected ValueError")


def _tool_trace(status: str = "success") -> RuntimeTrace:
    return RuntimeTrace(
        session_id="session-1",
        user_id="user-1",
        user_message="Summarize README and run tests",
        final_response="Done.",
        status=status,
        tool_executions=[
            ToolExecutionTrace(
                iteration=1,
                tool_call_id="call-1",
                tool_name="read_file",
                status="success",
            ),
            ToolExecutionTrace(
                iteration=2,
                tool_call_id="call-2",
                tool_name="bash",
                status="success",
            ),
        ],
    )
