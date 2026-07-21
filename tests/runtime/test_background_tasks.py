import threading
import time

from navi_agent.runtime import BackgroundTaskManager
from navi_agent.tooling import ToolResult


def _wait_for_terminal(manager: BackgroundTaskManager, task_id: str):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        task = manager.get(task_id, session_id="s1", user_id="u1")
        if task is not None and task.status in {"succeeded", "failed"}:
            return task
        time.sleep(0.01)
    raise AssertionError("background task did not finish")


def test_submit_returns_before_runner_completes() -> None:
    manager = BackgroundTaskManager()
    release = threading.Event()

    task = manager.submit(
        session_id="s1",
        user_id="u1",
        description="slow command",
        runner=lambda: (release.wait(), ToolResult.ok(name="bash", content="done"))[1],
    )

    assert task.status in {"queued", "running"}
    assert manager.get(task.task_id, session_id="other", user_id="u1") is None
    release.set()
    completed = _wait_for_terminal(manager, task.task_id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result.content == "done"


def test_completed_notifications_are_drained_once_and_scoped() -> None:
    manager = BackgroundTaskManager()
    task = manager.submit(
        session_id="s1",
        user_id="u1",
        description="failing command",
        runner=lambda: ToolResult.error(name="bash", content="exit_code: 1"),
    )
    _wait_for_terminal(manager, task.task_id)

    assert manager.drain_completed(session_id="s2", user_id="u1") == []
    notifications = manager.drain_completed(session_id="s1", user_id="u1")
    assert [item.task_id for item in notifications] == [task.task_id]
    assert notifications[0].status == "failed"
    assert manager.drain_completed(session_id="s1", user_id="u1") == []


def test_completion_listeners_are_notified_and_fail_open() -> None:
    manager = BackgroundTaskManager()
    notified = threading.Event()
    received = []

    def failing_listener(_task) -> None:
        raise RuntimeError("listener failed")

    def recording_listener(task) -> None:
        received.append(task)
        notified.set()

    manager.add_completion_listener(failing_listener)
    manager.add_completion_listener(recording_listener)
    task = manager.submit(
        session_id="s1",
        user_id="u1",
        description="tests",
        runner=lambda: ToolResult.ok(name="bash", content="passed"),
    )

    assert notified.wait(timeout=2)
    assert received[0].task_id == task.task_id
    assert received[0].status == "succeeded"
