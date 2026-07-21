from navi_agent.runtime import SubagentRun
from navi_agent.tooling import ToolContext
from navi_agent.tools import DelegateTaskTool


class FakeSubagentService:
    def __init__(self, run: SubagentRun | list[SubagentRun]) -> None:
        self._run = run
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._run

    def run_many(self, **kwargs):
        self.calls.append(kwargs)
        return self._run


def test_delegate_task_returns_only_child_final_report() -> None:
    service = FakeSubagentService(
        SubagentRun(
            session_id="parent:subagent:child",
            status="success",
            final_response="architecture report",
            toolsets=("file",),
        )
    )
    tool = DelegateTaskTool(service)

    result = tool.invoke(
        context=ToolContext(session_id="parent", user_id="user", iteration=1),
        goal="Review architecture",
        task_context="Inspect runtime files",
        toolsets=["file"],
    )

    assert result.status == "success"
    assert result.content == "architecture report"
    assert result.structured_content == {
        "child_session_id": "parent:subagent:child",
        "mode": "single",
        "runs": [
            {
                "child_session_id": "parent:subagent:child",
                "status": "success",
                "toolsets": ["file"],
            }
        ],
        "status": "success",
        "toolsets": ["file"],
    }
    assert service.calls[0]["parent_session_id"] == "parent"
    assert service.calls[0]["user_id"] == "user"


def test_delegate_task_requires_runtime_context() -> None:
    service = FakeSubagentService(
        SubagentRun("child", "success", "report", ("file",))
    )

    result = DelegateTaskTool(service).invoke(goal="Review", task_context="files")

    assert result.status == "error"
    assert result.content == "delegate_task requires runtime context"


def test_delegate_task_renders_parallel_results_in_input_order() -> None:
    service = FakeSubagentService(
        [
            SubagentRun("parent:subagent:first", "success", "first report", ("file",)),
            SubagentRun("parent:subagent:second", "success", "second report", ("skills",)),
        ]
    )
    tool = DelegateTaskTool(service)

    result = tool.invoke(
        context=ToolContext(session_id="parent", user_id="user", iteration=1),
        tasks=[
            {"goal": "First", "task_context": "A", "toolsets": ["file"]},
            {"goal": "Second", "task_context": "B", "toolsets": ["skills"]},
        ],
    )

    assert result.status == "success"
    assert result.content.index("first report") < result.content.index("second report")
    assert result.structured_content["mode"] == "batch"
    assert len(result.structured_content["runs"]) == 2
    assert service.calls[0]["tasks"][0].goal == "First"


def test_delegate_task_rejects_mixed_single_and_batch_modes() -> None:
    service = FakeSubagentService(
        SubagentRun("child", "success", "report", ("file",))
    )

    result = DelegateTaskTool(service).invoke(
        context=ToolContext(session_id="parent", user_id="user", iteration=1),
        goal="Single",
        task_context="single context",
        tasks=[{"goal": "Batch", "task_context": "batch context"}],
    )

    assert result.status == "error"
    assert result.content == "provide either goal/task_context or tasks"
    assert service.calls == []
