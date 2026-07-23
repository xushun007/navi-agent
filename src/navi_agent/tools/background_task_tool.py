from __future__ import annotations

from typing import TYPE_CHECKING, Any

from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool

if TYPE_CHECKING:
    from navi_agent.runtime.tasks.background import BackgroundTask, BackgroundTaskManager


class BackgroundTaskTool(BaseTool):
    def __init__(self, manager: BackgroundTaskManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "background_task"

    @property
    def description(self) -> str:
        return "Inspect background command tasks for the current conversation."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "list"]},
                "task_id": {"type": "string"},
            },
            "required": ["action"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(name=self.name, content="Background task context is required")
        action = str(kwargs.get("action") or "").strip()
        if action == "status":
            task_id = str(kwargs.get("task_id") or "").strip()
            if not task_id:
                return ToolResult.error(name=self.name, content="task_id is required for status")
            task = self._manager.get(
                task_id,
                session_id=context.session_id,
                user_id=context.user_id,
            )
            if task is None:
                return ToolResult.error(name=self.name, content=f"Background task not found: {task_id}")
            return ToolResult.ok(
                name=self.name,
                content=self._render_task(task),
                structured_content=self._serialize_task(task),
            )
        if action == "list":
            tasks = self._manager.list(
                session_id=context.session_id,
                user_id=context.user_id,
            )
            content = "No background tasks" if not tasks else "\n\n".join(
                self._render_task(task) for task in tasks
            )
            return ToolResult.ok(
                name=self.name,
                content=content,
                structured_content={"tasks": [self._serialize_task(task) for task in tasks]},
            )
        return ToolResult.error(name=self.name, content=f"Unsupported action: {action or '-'}")

    @staticmethod
    def _serialize_task(task: BackgroundTask) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task_id": task.task_id,
            "description": task.description,
            "status": task.status,
            "submitted_at": task.submitted_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
        }
        if task.result is not None:
            payload["result"] = {
                "name": task.result.name,
                "status": task.result.status,
                "content": task.result.content,
                "structured_content": dict(task.result.structured_content),
            }
        return payload

    @staticmethod
    def _render_task(task: BackgroundTask) -> str:
        lines = [
            f"task_id: {task.task_id}",
            f"status: {task.status}",
            f"description: {task.description}",
        ]
        if task.result is not None:
            lines.append(f"result:\n{task.result.content}")
        return "\n".join(lines)
