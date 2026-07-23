from __future__ import annotations

from typing import Any

from navi_agent.runtime.tasks.subagents import (
    ALLOWED_SUBAGENT_TOOLSETS,
    MAX_CONCURRENT_SUBAGENTS,
    SubagentRun,
    SubagentService,
    SubagentTask,
)
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
            "Delegate one focused task or up to three independent parallel tasks to isolated "
            "subagents. Each child receives only its supplied goal and context and returns only "
            "its final report. Parallel children cannot request interactive approvals."
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
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_CONCURRENT_SUBAGENTS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string"},
                            "task_context": {"type": "string"},
                            "toolsets": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": sorted(ALLOWED_SUBAGENT_TOOLSETS),
                                },
                            },
                        },
                        "required": ["goal", "task_context"],
                        "additionalProperties": False,
                    },
                    "description": "Independent tasks to execute concurrently.",
                },
            },
            "additionalProperties": False,
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(
                name=self.name,
                content="delegate_task requires runtime context",
            )

        raw_tasks = kwargs.get("tasks")
        has_single = bool(str(kwargs.get("goal") or "").strip())
        has_batch = isinstance(raw_tasks, list) and bool(raw_tasks)
        if has_single == has_batch:
            return ToolResult.error(
                name=self.name,
                content="provide either goal/task_context or tasks",
            )

        try:
            runs = (
                self._service.run_many(
                    tasks=self._parse_tasks(raw_tasks),
                    parent_session_id=context.session_id,
                    user_id=context.user_id,
                )
                if has_batch
                else [
                    self._service.run(
                        goal=str(kwargs.get("goal") or ""),
                        context=str(kwargs.get("task_context") or ""),
                        parent_session_id=context.session_id,
                        user_id=context.user_id,
                        toolsets=kwargs.get("toolsets"),
                    )
                ]
            )
        except (TypeError, ValueError) as exc:
            return ToolResult.error(name=self.name, content=str(exc))

        structured_runs = [self._structured_run(run) for run in runs]
        failed = [run for run in runs if run.status != "success"]
        content = self._render_runs(runs)
        structured_content = {
            "mode": "batch" if has_batch else "single",
            "runs": structured_runs,
        }
        if not has_batch:
            structured_content.update(structured_runs[0])
        if failed:
            return ToolResult.error(
                name=self.name,
                content=content,
                structured_content=structured_content,
            )
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content=structured_content,
        )

    @staticmethod
    def _parse_tasks(raw_tasks: Any) -> list[SubagentTask]:
        if not isinstance(raw_tasks, list):
            raise ValueError("tasks must be an array")
        tasks = []
        for index, item in enumerate(raw_tasks, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"task {index} must be an object")
            tasks.append(
                SubagentTask(
                    goal=str(item.get("goal") or ""),
                    context=str(item.get("task_context") or ""),
                    toolsets=item.get("toolsets"),
                )
            )
        return tasks

    @staticmethod
    def _structured_run(run: SubagentRun) -> dict[str, Any]:
        return {
            "child_session_id": run.session_id,
            "status": run.status,
            "toolsets": list(run.toolsets),
        }

    @staticmethod
    def _render_runs(runs: list[SubagentRun]) -> str:
        if len(runs) == 1:
            run = runs[0]
            if run.status == "success":
                return run.final_response
            return (
                f"Subagent failed: status={run.status} child_session_id={run.session_id}\n"
                f"{run.final_response}"
            ).strip()

        sections = []
        for index, run in enumerate(runs, start=1):
            sections.append(
                "\n".join(
                    [
                        f"## Subagent {index}",
                        f"status: {run.status}",
                        f"child_session_id: {run.session_id}",
                        run.final_response,
                    ]
                ).strip()
            )
        return "\n\n".join(sections)
