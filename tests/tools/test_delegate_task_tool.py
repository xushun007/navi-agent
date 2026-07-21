from navi_agent.runtime import SubagentRun
from navi_agent.tooling import ToolContext
from navi_agent.tools import DelegateTaskTool


class FakeSubagentService:
    def __init__(self, run: SubagentRun) -> None:
        self._run = run
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):
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
