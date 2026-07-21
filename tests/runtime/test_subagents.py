from navi_agent.runtime import Message, RuntimeResult, SubagentService


class RecordingRuntime:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    def run_conversation(self, session_id, user_id, user_message, system_prompt=None):
        self._calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "user_message": user_message,
                "system_prompt": system_prompt,
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

    def build_runtime(toolsets: list[str], parent_session_id: str) -> RecordingRuntime:
        selected_toolsets.append(toolsets)
        assert parent_session_id == "parent-1"
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


def test_subagent_rejects_non_worker_toolsets() -> None:
    service = SubagentService(runtime_factory=lambda _tools, _parent: RecordingRuntime([]))

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
