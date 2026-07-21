from __future__ import annotations

from typing import Any

from navi_agent.runtime.subagents import ALLOWED_SUBAGENT_TOOLSETS, SubagentService
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


class DelegateTaskTool(BaseTool):
    def __init__(self, service: SubagentService) -> None:
        self._service = service

    @property
    def name(self) -> str:
        return "delegate_task"

    @property
    def description(self) -> str:
        return (
            "Delegate one focused task to an isolated subagent. The child receives only the supplied "
            "goal and context, runs with a restricted toolset, and returns only its final report."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "A complete, independently executable goal.",
                },
                "task_context": {
                    "type": "string",
                    "description": "All parent context the isolated subagent needs.",
                },
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(ALLOWED_SUBAGENT_TOOLSETS)},
                    "description": "Restricted child capabilities. Defaults to file and skills.",
                },
            },
            "required": ["goal", "task_context"],
            "additionalProperties": False,
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(
                name=self.name,
                content="delegate_task requires runtime context",
            )

        try:
            run = self._service.run(
                goal=str(kwargs.get("goal") or ""),
                context=str(kwargs.get("task_context") or ""),
                parent_session_id=context.session_id,
                user_id=context.user_id,
                toolsets=kwargs.get("toolsets"),
            )
        except (TypeError, ValueError) as exc:
            return ToolResult.error(name=self.name, content=str(exc))

        structured_content = {
            "child_session_id": run.session_id,
            "status": run.status,
            "toolsets": list(run.toolsets),
        }
        if run.status != "success":
            return ToolResult.error(
                name=self.name,
                content=(
                    f"Subagent failed: status={run.status} child_session_id={run.session_id}\n"
                    f"{run.final_response}"
                ).strip(),
                structured_content=structured_content,
            )
        return ToolResult.ok(
            name=self.name,
            content=run.final_response,
            structured_content=structured_content,
        )
