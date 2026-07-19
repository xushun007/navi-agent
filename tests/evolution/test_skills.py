from pathlib import Path

from navi_agent.evolution import EvolutionCandidate, EvolutionEngine, FileSkillStore
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


def test_applies_update_skill_candidate_to_store(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="# Old\n")
    candidate = EvolutionCandidate(
        target="skill",
        summary="Update skill",
        rationale="New procedure",
        status="accepted",
        metadata={
            "operation": "update",
            "skill_name": "readme-summary",
            "section": "## Procedure",
            "append_content": "- Verify README after editing.",
        },
    )

    record = EvolutionEngine().apply_skill_candidate(candidate, skill_store=store)

    assert record is not None
    assert "# Old" in record.content
    assert "## Procedure" in record.content
    assert "- Verify README after editing." in record.content


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


def test_archives_skill_directory(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="# README Summary\n")

    archived = store.archive("readme-summary")

    assert archived is not None
    assert archived.path == tmp_path / ".archive" / "readme-summary" / "SKILL.md"
    assert archived.path.exists()
    assert store.get("readme-summary") is None


def test_update_missing_skill_returns_none(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)

    record = store.update(name="missing-skill", content="# Missing\n")

    assert record is None


def test_append_to_existing_skill_section(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-summary",
        content="# README Summary\n\n## Procedure\n\n- Read README.\n\n## Evidence\n\n- trace",
    )

    record = store.append_to_section(
        name="readme-summary",
        section="## Procedure",
        content="- Verify README.",
    )

    assert record is not None
    assert "## Procedure\n\n- Read README.\n\n- Verify README.\n\n## Evidence" in record.content


def test_list_reads_skill_metadata(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-summary",
        content="\n".join(
            [
                "---",
                "description: Summarize README files and run tests",
                "category: coding",
                "---",
                "Use read_file before bash.",
            ]
        ),
    )

    records = store.list()

    assert [record.name for record in records] == ["readme-summary"]
    assert records[0].description == "Summarize README files and run tests"
    assert records[0].category == "coding"


def test_reads_skill_references(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="description: Summarize README files")
    references_dir = tmp_path / "readme-summary" / "references"
    references_dir.mkdir()
    (references_dir / "checks.md").write_text("Run README checks after editing.", encoding="utf-8")

    record = store.get("readme-summary")

    assert record is not None
    assert len(record.references) == 1
    assert record.references[0].path == "references/checks.md"
    assert "README checks" in record.references[0].content


def test_writes_skill_attachment(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="description: Summarize README files")

    attachment = store.write_attachment(
        name="readme-summary",
        relative_path="templates/report.md",
        content="# Report\n\n{summary}\n",
    )

    assert attachment is not None
    assert attachment.path == "templates/report.md"
    assert attachment.kind == "templates"
    assert (tmp_path / "readme-summary" / "templates" / "report.md").read_text(
        encoding="utf-8"
    ) == "# Report\n\n{summary}\n"
    record = store.get("readme-summary")
    assert record is not None
    assert [item.path for item in record.attachments] == ["templates/report.md"]


def test_reads_skill_attachment(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="description: Summarize README files")
    store.write_attachment(
        name="readme-summary",
        relative_path="references/checks.md",
        content="Run README checks after editing.",
    )

    content = store.read_attachment(
        name="readme-summary",
        relative_path="references/checks.md",
    )

    assert content == "Run README checks after editing."


def test_read_skill_attachment_returns_none_for_missing_file(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="description: Summarize README files")

    content = store.read_attachment(
        name="readme-summary",
        relative_path="references/missing.md",
    )

    assert content is None


def test_read_skill_attachment_rejects_unsafe_path(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="description: Summarize README files")

    try:
        store.read_attachment(name="readme-summary", relative_path="../outside.md")
    except ValueError as error:
        assert "parent segments" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_write_skill_attachment_requires_existing_skill(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)

    attachment = store.write_attachment(
        name="missing-skill",
        relative_path="references/error.md",
        content="details",
    )

    assert attachment is None


def test_write_skill_attachment_rejects_unsafe_path(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="description: Summarize README files")

    try:
        store.write_attachment(
            name="readme-summary",
            relative_path="../outside.md",
            content="bad",
        )
    except ValueError as error:
        assert "parent segments" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_write_skill_attachment_rejects_unknown_directory(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(name="readme-summary", content="description: Summarize README files")

    try:
        store.write_attachment(
            name="readme-summary",
            relative_path="notes/detail.md",
            content="bad",
        )
    except ValueError as error:
        assert "references" in str(error)
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
