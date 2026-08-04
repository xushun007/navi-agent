import time
from threading import Barrier, Event

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
        cancellation_token=None,
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
            cancellation_token=None,
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


def test_subagent_batch_times_out_only_unfinished_tasks() -> None:
    stopped = Event()

    class Runtime:
        def run_conversation(self, session_id, user_message, cancellation_token, **kwargs):
            if "Slow task" not in user_message:
                return RuntimeResult(session_id=session_id, status="success", final_response="done")
            while not cancellation_token.is_cancelled:
                time.sleep(0.005)
            stopped.set()
            return RuntimeResult(session_id=session_id, status="cancelled", final_response="")

    service = SubagentService(
        runtime_factory=lambda _tools, _parent, _non_interactive: Runtime(),
        deadline_seconds=0.05,
    )
    runs = service.run_many(
        tasks=[SubagentTask("Slow task", ""), SubagentTask("Fast task", "")],
        parent_session_id="parent-1",
        user_id="user-1",
    )

    assert [run.status for run in runs] == ["timed_out", "success"]
    assert stopped.wait(0.5)


def test_subagent_propagates_parent_cancellation() -> None:
    parent_cancelled = Event()
    parent_cancelled.set()

    class Runtime:
        def run_conversation(self, session_id, cancellation_token, **kwargs):
            while not cancellation_token.is_cancelled:
                time.sleep(0.005)
            return RuntimeResult(session_id=session_id, status="cancelled", final_response="")

    service = SubagentService(
        runtime_factory=lambda _tools, _parent, _non_interactive: Runtime(),
    )

    run = service.run(
        goal="Inspect runtime",
        context="",
        parent_session_id="parent-1",
        user_id="user-1",
        cancellation_requested=parent_cancelled.is_set,
    )

    assert run.status == "cancelled"


def test_subagent_bounds_input_and_result_size() -> None:
    class Runtime:
        def run_conversation(self, session_id, **kwargs):
            return RuntimeResult(
                session_id=session_id,
                status="success",
                final_response="start" + "x" * 20_000 + "end",
            )

    service = SubagentService(
        runtime_factory=lambda _tools, _parent, _non_interactive: Runtime()
    )
    run = service.run(
        goal="Inspect runtime",
        context="",
        parent_session_id="parent-1",
        user_id="user-1",
    )

    assert run.truncated is True
    assert len(run.final_response) <= 20_000
    assert run.final_response.startswith("start")
    assert run.final_response.endswith("end")

    try:
        service.run(
            goal="Inspect runtime",
            context="x" * 32_000,
            parent_session_id="parent-1",
            user_id="user-1",
        )
    except ValueError as exc:
        assert str(exc) == "delegated task input is too large"
    else:
        raise AssertionError("expected oversized input error")


def test_subagent_converts_runtime_exception_to_failed_result() -> None:
    class Runtime:
        def run_conversation(self, **kwargs):
            raise RuntimeError("private detail")

    service = SubagentService(
        runtime_factory=lambda _tools, _parent, _non_interactive: Runtime()
    )
    run = service.run(
        goal="Inspect runtime",
        context="",
        parent_session_id="parent-1",
        user_id="user-1",
    )

    assert run.status == "failed"
    assert run.final_response == "Subagent failed: RuntimeError"
    assert run.duration_seconds >= 0
