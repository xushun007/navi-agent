import time

from navi_agent.runtime import BackgroundTaskManager, ToolContext
from navi_agent.tooling import ToolResult
from navi_agent.tools import BackgroundTaskTool


def test_lists_and_reads_tasks_for_current_session() -> None:
    manager = BackgroundTaskManager()
    task = manager.submit(
        session_id="s1",
        user_id="u1",
        description="tests",
        runner=lambda: ToolResult.ok(name="bash", content="passed"),
    )
    deadline = time.monotonic() + 2
    while manager.get(task.task_id, session_id="s1", user_id="u1").status not in {
        "succeeded",
        "failed",
    }:
        if time.monotonic() >= deadline:
            raise AssertionError("background task did not finish")
        time.sleep(0.01)

    tool = BackgroundTaskTool(manager)
    context = ToolContext(session_id="s1", user_id="u1", iteration=1)
    status = tool.invoke(context=context, action="status", task_id=task.task_id)
    listing = tool.invoke(context=context, action="list")

    assert status.status == "success"
    assert status.structured_content["status"] == "succeeded"
    assert status.structured_content["result"]["content"] == "passed"
    assert listing.structured_content["tasks"][0]["task_id"] == task.task_id


def test_does_not_expose_tasks_from_another_session() -> None:
    manager = BackgroundTaskManager()
    task = manager.submit(
        session_id="s1",
        user_id="u1",
        description="private",
        runner=lambda: ToolResult.ok(name="bash", content="done"),
    )
    tool = BackgroundTaskTool(manager)

    result = tool.invoke(
        context=ToolContext(session_id="s2", user_id="u1", iteration=1),
        action="status",
        task_id=task.task_id,
    )

    assert result.status == "error"
    assert "not found" in result.content
