from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import threading
from uuid import uuid4

from navi_agent.tooling import ToolResult

logger = logging.getLogger("navi_agent.runtime.background_tasks")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(slots=True)
class BackgroundTask:
    task_id: str
    session_id: str
    user_id: str
    description: str
    status: str = "queued"
    submitted_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    result: ToolResult | None = None
    notification_delivered: bool = False


class BackgroundTaskManager:
    def __init__(self, max_concurrent_tasks: int = 4, max_pending_tasks: int = 32) -> None:
        if max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be at least 1")
        if max_pending_tasks < max_concurrent_tasks:
            raise ValueError("max_pending_tasks must be at least max_concurrent_tasks")
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(max_concurrent_tasks)
        self._max_pending_tasks = max_pending_tasks
        self._completion_listeners: list[Callable[[BackgroundTask], None]] = []

    def add_completion_listener(self, listener: Callable[[BackgroundTask], None]) -> None:
        with self._lock:
            self._completion_listeners.append(listener)

    def submit(
        self,
        *,
        session_id: str,
        user_id: str,
        description: str,
        runner: Callable[[], ToolResult],
    ) -> BackgroundTask:
        with self._lock:
            active_count = sum(
                task.status in {"queued", "running"} for task in self._tasks.values()
            )
            if active_count >= self._max_pending_tasks:
                raise RuntimeError("Background task capacity reached")
            task = BackgroundTask(
                task_id=uuid4().hex,
                session_id=session_id,
                user_id=user_id,
                description=description,
                submitted_at=_utc_now_iso(),
            )
            self._tasks[task.task_id] = task
            snapshot = replace(task)

        thread = threading.Thread(
            target=self._run,
            args=(task.task_id, runner),
            name=f"navi-background-{task.task_id[:8]}",
            daemon=True,
        )
        thread.start()
        return snapshot

    def get(self, task_id: str, *, session_id: str, user_id: str) -> BackgroundTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.session_id != session_id or task.user_id != user_id:
                return None
            return replace(task)

    def list(self, *, session_id: str, user_id: str) -> list[BackgroundTask]:
        with self._lock:
            tasks = [
                replace(task)
                for task in self._tasks.values()
                if task.session_id == session_id and task.user_id == user_id
            ]
        return sorted(tasks, key=lambda task: task.submitted_at, reverse=True)

    def drain_completed(self, *, session_id: str, user_id: str) -> list[BackgroundTask]:
        with self._lock:
            completed = [
                task
                for task in self._tasks.values()
                if task.session_id == session_id
                and task.user_id == user_id
                and task.status in {"succeeded", "failed"}
                and not task.notification_delivered
            ]
            for task in completed:
                task.notification_delivered = True
            snapshots = [replace(task) for task in completed]
        return sorted(snapshots, key=lambda task: task.completed_at or "")

    def _run(self, task_id: str, runner: Callable[[], ToolResult]) -> None:
        with self._slots:
            with self._lock:
                task = self._tasks[task_id]
                task.status = "running"
                task.started_at = _utc_now_iso()
            try:
                result = runner()
            except Exception as exc:
                result = ToolResult.error(
                    name="background_task",
                    content=f"Background task failed: {exc}",
                    structured_content={"error_type": exc.__class__.__name__},
                )
            with self._lock:
                task = self._tasks[task_id]
                task.result = result
                task.status = "succeeded" if result.status == "success" else "failed"
                task.completed_at = _utc_now_iso()
                snapshot = replace(task)
                listeners = list(self._completion_listeners)
            for listener in listeners:
                try:
                    listener(snapshot)
                except Exception:
                    logger.exception("Background task completion listener failed: task_id=%s", task_id)
