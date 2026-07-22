from threading import Barrier

from navi_agent.runtime import Message, RuntimeResult, SubagentService, SubagentTask


class RecordingRuntime:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    def run_conversation(
        self,
        session_id,
        user_id,
        user_message,
        system_prompt=None,
        source="console",
    ):
        self._calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "user_message": user_message,
                "system_prompt": system_prompt,
                "source": source,
            }
        )
        return RuntimeResult(
            session_id=session_id,
            status="success",
            final_response="isolated report",
            messages=[Message(role="assistant", content="isolated report")],
        )


def test_subagent_runs_in_child_session_with_only_delegated_context() -> None:
    calls: list[dict[str, object]] = []
    selected_toolsets: list[list[str]] = []

    def build_runtime(
        toolsets: list[str],
        parent_session_id: str,
        non_interactive: bool,
    ) -> RecordingRuntime:
        selected_toolsets.append(toolsets)
        assert parent_session_id == "parent-1"
        assert non_interactive is False
        return RecordingRuntime(calls)

    service = SubagentService(runtime_factory=build_runtime)

    result = service.run(
        goal="Inspect the runtime architecture",
        context="Focus on src/navi_agent/runtime.",
        parent_session_id="parent-1",
        user_id="user-1",
        toolsets=["file", "skills"],
    )

    assert result.status == "success"
    assert result.final_response == "isolated report"
    assert result.session_id.startswith("parent-1:subagent:")
    assert selected_toolsets == [["file", "skills"]]
    assert calls[0]["session_id"] == result.session_id
    assert "Inspect the runtime architecture" in str(calls[0]["user_message"])
    assert "Focus on src/navi_agent/runtime." in str(calls[0]["user_message"])
    assert "parent conversation" in str(calls[0]["system_prompt"])
    assert calls[0]["source"] == "subagent"


def test_subagent_rejects_non_worker_toolsets() -> None:
    service = SubagentService(
        runtime_factory=lambda _tools, _parent, _non_interactive: RecordingRuntime([])
    )

    try:
        service.run(
            goal="Remember this",
            context="",
            parent_session_id="parent-1",
            user_id="user-1",
            toolsets=["memory"],
        )
    except ValueError as exc:
        assert str(exc) == "unsupported subagent toolsets: memory"
    else:
        raise AssertionError("expected unsupported toolset error")


def test_subagent_batch_runs_concurrently_and_preserves_task_order() -> None:
    barrier = Barrier(2, timeout=2)
    factory_calls: list[tuple[list[str], str, bool]] = []

    class ConcurrentRuntime:
        def run_conversation(
            self,
            session_id,
            user_id,
            user_message,
            system_prompt=None,
            source="console",
        ):
            assert source == "subagent"
            barrier.wait()
            goal = "first" if "First task" in user_message else "second"
            return RuntimeResult(
                session_id=session_id,
                status="success",
                final_response=f"{goal} report",
            )

    def build_runtime(toolsets, parent_session_id, non_interactive):
        factory_calls.append((toolsets, parent_session_id, non_interactive))
        return ConcurrentRuntime()

    service = SubagentService(runtime_factory=build_runtime)

    runs = service.run_many(
        tasks=[
            SubagentTask("First task", "First context", ["file"]),
            SubagentTask("Second task", "Second context", ["skills"]),
        ],
        parent_session_id="parent-1",
        user_id="user-1",
    )

    assert [run.final_response for run in runs] == ["first report", "second report"]
    assert len({run.session_id for run in runs}) == 2
    assert all(call[1:] == ("parent-1", True) for call in factory_calls)


def test_subagent_batch_enforces_concurrency_limit() -> None:
    service = SubagentService(
        runtime_factory=lambda _tools, _parent, _non_interactive: RecordingRuntime([])
    )

    try:
        service.run_many(
            tasks=[SubagentTask(f"task-{index}", "context") for index in range(4)],
            parent_session_id="parent-1",
            user_id="user-1",
        )
    except ValueError as exc:
        assert str(exc) == "subagent batch exceeds maximum of 3 tasks"
    else:
        raise AssertionError("expected concurrency limit error")
