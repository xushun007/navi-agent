from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from navi_agent.tooling import ToolResult

logger = logging.getLogger("navi_agent.runtime.tasks.background")


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
    cancel_requested: bool = False
    cancel_callback: Callable[[], None] | None = None


class BackgroundTaskStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save(self, task: BackgroundTask) -> None:
        result_json = _serialize_result(task.result)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO background_tasks (
                    task_id, session_id, user_id, description, status,
                    submitted_at, started_at, completed_at, result_json,
                    notification_delivered, cancel_requested
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    result_json = excluded.result_json,
                    notification_delivered = excluded.notification_delivered,
                    cancel_requested = excluded.cancel_requested
                """,
                (
                    task.task_id,
                    task.session_id,
                    task.user_id,
                    task.description,
                    task.status,
                    task.submitted_at,
                    task.started_at,
                    task.completed_at,
                    result_json,
                    int(task.notification_delivered),
                    int(task.cancel_requested),
                ),
            )

    def list_tasks(self) -> list[BackgroundTask]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM background_tasks ORDER BY submitted_at, task_id"
            ).fetchall()
        return [_background_task(row) for row in rows]

    def recover_interrupted(self) -> int:
        completed_at = _utc_now_iso()
        result = ToolResult.error(
            name="background_task",
            content="Background task interrupted by process restart",
            structured_content={"interrupted": True, "resumable": False},
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE background_tasks
                SET status = 'interrupted', completed_at = ?, result_json = ?
                WHERE status IN ('queued', 'running')
                """,
                (completed_at, _serialize_result(result)),
            )
        return cursor.rowcount

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS background_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    notification_delivered INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_background_tasks_session
                ON background_tasks(session_id, user_id, submitted_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 250")
        return connection


class BackgroundTaskManager:
    def __init__(
        self,
        max_concurrent_tasks: int = 4,
        max_pending_tasks: int = 32,
        store: BackgroundTaskStore | None = None,
    ) -> None:
        if max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be at least 1")
        if max_pending_tasks < max_concurrent_tasks:
            raise ValueError("max_pending_tasks must be at least max_concurrent_tasks")
        self._store = store
        if self._store is not None:
            self._store.recover_interrupted()
        stored_tasks = self._store.list_tasks() if self._store is not None else []
        self._tasks: dict[str, BackgroundTask] = {
            task.task_id: task for task in stored_tasks
        }
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(max_concurrent_tasks)
        self._max_pending_tasks = max_pending_tasks
        self._completion_listeners: list[Callable[[BackgroundTask], None]] = []

    def add_completion_listener(self, listener: Callable[[BackgroundTask], None]) -> None:
        with self._lock:
            self._completion_listeners.append(listener)
            pending = [
                replace(task)
                for task in self._tasks.values()
                if task.status in {"succeeded", "failed", "interrupted"}
                and not task.notification_delivered
            ]
        for task in pending:
            try:
                listener(task)
            except Exception:
                logger.exception(
                    "Background task completion listener failed: task_id=%s",
                    task.task_id,
                )
                continue
            self._mark_notification_delivered(task.task_id)

    def submit(
        self,
        *,
        session_id: str,
        user_id: str,
        description: str,
        runner: Callable[[], ToolResult],
        cancel_callback: Callable[[], None] | None = None,
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
                cancel_callback=cancel_callback,
            )
            self._tasks[task.task_id] = task
            self._save(task)
            snapshot = replace(task)

        thread = threading.Thread(
            target=self._run,
            args=(task.task_id, runner),
            name=f"navi-background-{task.task_id[:8]}",
            daemon=True,
        )
        thread.start()
        return snapshot

    def cancel(self, task_id: str, *, session_id: str, user_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if (
                task is None
                or task.session_id != session_id
                or task.user_id != user_id
                or task.status not in {"queued", "running"}
                or task.cancel_callback is None
            ):
                return False
            task.cancel_requested = True
            self._save(task)
            cancel_callback = task.cancel_callback
        cancel_callback()
        return True

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
                and task.status in {"succeeded", "failed", "interrupted"}
                and not task.notification_delivered
            ]
            for task in completed:
                task.notification_delivered = True
                self._save(task)
            snapshots = [replace(task) for task in completed]
        return sorted(snapshots, key=lambda task: task.completed_at or "")

    def _run(self, task_id: str, runner: Callable[[], ToolResult]) -> None:
        with self._slots:
            with self._lock:
                task = self._tasks[task_id]
                task.status = "running"
                task.started_at = _utc_now_iso()
                self._save(task)
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
                self._save(task)
                snapshot = replace(task)
                listeners = list(self._completion_listeners)
            notification_delivered = False
            for listener in listeners:
                try:
                    listener(snapshot)
                    notification_delivered = True
                except Exception:
                    logger.exception("Background task completion listener failed: task_id=%s", task_id)
            if notification_delivered:
                self._mark_notification_delivered(task_id)

    def _mark_notification_delivered(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.notification_delivered:
                return
            task.notification_delivered = True
            self._save(task)

    def _save(self, task: BackgroundTask) -> None:
        if self._store is not None:
            self._store.save(task)


def _serialize_result(result: ToolResult | None) -> str | None:
    if result is None:
        return None
    return json.dumps(
        {
            "tool_call_id": result.tool_call_id,
            "name": result.name,
            "content": result.content,
            "status": result.status,
            "structured_content": result.structured_content,
            "metadata": result.metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _background_task(row: sqlite3.Row) -> BackgroundTask:
    result = None
    if row["result_json"]:
        payload = json.loads(str(row["result_json"]))
        result = ToolResult(
            tool_call_id=str(payload.get("tool_call_id") or ""),
            name=str(payload.get("name") or "background_task"),
            content=str(payload.get("content") or ""),
            status=str(payload.get("status") or "error"),
            structured_content=dict(payload.get("structured_content") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )
    return BackgroundTask(
        task_id=str(row["task_id"]),
        session_id=str(row["session_id"]),
        user_id=str(row["user_id"]),
        description=str(row["description"]),
        status=str(row["status"]),
        submitted_at=str(row["submitted_at"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        result=result,
        notification_delivered=bool(row["notification_delivered"]),
        cancel_requested=bool(row["cancel_requested"]),
    )
