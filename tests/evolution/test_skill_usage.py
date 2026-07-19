from pathlib import Path

from navi_agent.evolution import FileSkillStore, SkillUsageService, SkillUsageStore
from navi_agent.telemetry import InMemoryTraceStore, RuntimeTrace, ToolExecutionTrace


def test_summarizes_skill_usage_from_traces(tmp_path: Path) -> None:
    skill_store = FileSkillStore(tmp_path)
    skill_store.create(
        name="readme-summary",
        content="\n".join(
            [
                "---",
                "description: Summarize README files",
                "---",
            ]
        ),
    )
    trace_store = InMemoryTraceStore()
    trace_store.record(
        RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="a",
            final_response="ok",
            status="success",
            injected_skill_names=["readme-summary"],
            completed_at="2026-07-11T10:00:00+00:00",
        )
    )
    trace_store.record(
        RuntimeTrace(
            session_id="s2",
            user_id="u1",
            user_message="b",
            final_response="ok",
            status="success",
            injected_skill_names=["readme-summary", "missing-skill"],
            completed_at="2026-07-11T11:00:00+00:00",
        )
    )

    records = SkillUsageService(
        skill_store=skill_store,
        trace_store=trace_store,
    ).summarize()

    assert records[0].name == "readme-summary"
    assert records[0].description == "Summarize README files"
    assert records[0].injected_count == 2
    assert records[0].last_injected_at == "2026-07-11T11:00:00+00:00"
    assert records[1].name == "missing-skill"
    assert records[1].injected_count == 1


def test_summarizes_skill_usage_from_skill_view_tool_calls(tmp_path: Path) -> None:
    skill_store = FileSkillStore(tmp_path)
    skill_store.create(
        name="debug-crash",
        content="\n".join(
            [
                "---",
                "description: Debug process crashes",
                "---",
            ]
        ),
    )
    trace_store = InMemoryTraceStore()
    trace_store.record(
        RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="帮我修一下",
            final_response="ok",
            status="success",
            tool_executions=[
                ToolExecutionTrace(
                    iteration=1,
                    tool_call_id="tc1",
                    tool_name="skill_manage",
                    status="success",
                    arguments={"action": "view", "skill_name": "debug-crash"},
                )
            ],
            completed_at="2026-07-11T10:00:00+00:00",
        )
    )

    records = SkillUsageService(
        skill_store=skill_store,
        trace_store=trace_store,
    ).summarize()

    assert records[0].name == "debug-crash"
    assert records[0].injected_count == 1
    assert records[0].last_injected_at == "2026-07-11T10:00:00+00:00"


def test_includes_unused_skills(tmp_path: Path) -> None:
    skill_store = FileSkillStore(tmp_path)
    skill_store.create(
        name="unused-skill",
        content="\n".join(
            [
                "---",
                "description: Unused skill",
                "---",
            ]
        ),
    )

    records = SkillUsageService(
        skill_store=skill_store,
        trace_store=InMemoryTraceStore(),
    ).summarize()

    assert len(records) == 1
    assert records[0].name == "unused-skill"
    assert records[0].injected_count == 0
    assert records[0].last_injected_at is None


def test_summarizes_skill_usage_sidecar_events(tmp_path: Path) -> None:
    skill_store = FileSkillStore(tmp_path)
    skill_store.create(
        name="readme-summary",
        content="description: Summarize README files",
    )
    usage_store = SkillUsageStore(tmp_path)
    usage_store.record_create("readme-summary")
    usage_store.record_update("readme-summary")
    usage_store.record_archive("old-skill")

    records = SkillUsageService(
        skill_store=skill_store,
        trace_store=InMemoryTraceStore(),
        usage_store=usage_store,
    ).summarize()

    by_name = {record.name: record for record in records}
    assert by_name["readme-summary"].created_count == 1
    assert by_name["readme-summary"].updated_count == 1
    assert by_name["readme-summary"].archived_count == 0
    assert by_name["old-skill"].archived_count == 1
