from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from navi_agent.runtime.tasks.cron import CronJobStore, CronSchedulerService, parse_run_at
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


class CronTool(BaseTool):
    def __init__(self, store: CronJobStore) -> None:
        self._scheduler = CronSchedulerService(store)

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return (
            "Schedule proactive agent execution. Use it to create one-time timers, "
            "create recurring cron jobs, list jobs, or cancel jobs."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["once", "cron", "list", "cancel"],
                    "description": "once schedules a one-time run; cron schedules a recurring job; list shows jobs; cancel disables a job.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Prompt to inject when the schedule fires. Required for once and cron.",
                },
                "run_at": {
                    "type": "string",
                    "description": "ISO datetime for a one-time run, e.g. 2026-07-21T09:00:00+08:00.",
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Alternative to run_at for one-time runs.",
                },
                "cron": {
                    "type": "string",
                    "description": "Five-field cron expression: minute hour day month weekday. Supports *, */n, numbers, and comma lists.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session to wake. Defaults to the current session.",
                },
                "id": {
                    "type": "string",
                    "description": "Job id. Required for cancel.",
                },
            },
            "required": ["action"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(name=self.name, content="cron_error: tool context required")
        action = str(kwargs.get("action", "")).strip().lower()
        if action == "list":
            return self._list_jobs()
        if action == "cancel":
            return self._cancel(kwargs)
        if action in {"once", "cron"}:
            prompt = str(kwargs.get("prompt", "")).strip()
            if not prompt:
                return ToolResult.error(name=self.name, content="cron_error: prompt is required")
            session_id = str(kwargs.get("session_id") or context.session_id).strip()
            if action == "once":
                return self._create_once(context=context, prompt=prompt, session_id=session_id, kwargs=kwargs)
            return self._create_cron(context=context, prompt=prompt, session_id=session_id, kwargs=kwargs)
        return ToolResult.error(name=self.name, content=f"cron_error: unsupported action: {action}")

    def _create_once(
        self,
        *,
        context: ToolContext,
        prompt: str,
        session_id: str,
        kwargs: dict[str, Any],
    ) -> ToolResult:
        try:
            if kwargs.get("run_at"):
                run_at = parse_run_at(str(kwargs["run_at"]))
            else:
                delay_seconds = int(kwargs.get("delay_seconds", 0))
                if delay_seconds <= 0:
                    return ToolResult.error(
                        name=self.name,
                        content="cron_error: run_at or positive delay_seconds is required for once",
                    )
                run_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
            job = self._scheduler.create_once(
                prompt=prompt,
                user_id=context.user_id,
                session_id=session_id,
                run_at=run_at,
            )
        except ValueError as error:
            return ToolResult.error(name=self.name, content=f"cron_error: {error}")
        return ToolResult.ok(
            name=self.name,
            content=f"cron_scheduled: {job.id} once next_run_at={job.next_run_at}",
            structured_content={
                "id": job.id,
                "schedule_type": job.schedule_type,
                "next_run_at": job.next_run_at,
                "session_id": job.session_id,
            },
        )

    def _create_cron(
        self,
        *,
        context: ToolContext,
        prompt: str,
        session_id: str,
        kwargs: dict[str, Any],
    ) -> ToolResult:
        expression = str(kwargs.get("cron", "")).strip()
        if not expression:
            return ToolResult.error(name=self.name, content="cron_error: cron expression is required")
        try:
            job = self._scheduler.create_cron(
                prompt=prompt,
                user_id=context.user_id,
                session_id=session_id,
                cron=expression,
            )
        except ValueError as error:
            return ToolResult.error(name=self.name, content=f"cron_error: {error}")
        return ToolResult.ok(
            name=self.name,
            content=f"cron_scheduled: {job.id} cron='{job.cron}' next_run_at={job.next_run_at}",
            structured_content={
                "id": job.id,
                "schedule_type": job.schedule_type,
                "cron": job.cron,
                "next_run_at": job.next_run_at,
                "session_id": job.session_id,
            },
        )

    def _list_jobs(self) -> ToolResult:
        jobs = self._scheduler.list_jobs()
        if not jobs:
            return ToolResult.ok(name=self.name, content="cron_empty", structured_content={"jobs": []})
        lines = []
        serialized = []
        for job in jobs:
            status = "enabled" if job.enabled else "disabled"
            lines.append(f"{job.id} [{status}] {job.schedule_type} next={job.next_run_at or '-'} session={job.session_id}")
            serialized.append(
                {
                    "id": job.id,
                    "enabled": job.enabled,
                    "schedule_type": job.schedule_type,
                    "cron": job.cron,
                    "next_run_at": job.next_run_at,
                    "last_run_at": job.last_run_at,
                    "session_id": job.session_id,
                    "user_id": job.user_id,
                    "prompt": job.prompt,
                }
            )
        return ToolResult.ok(
            name=self.name,
            content="\n".join(lines),
            structured_content={"jobs": serialized},
        )

    def _cancel(self, kwargs: dict[str, Any]) -> ToolResult:
        job_id = str(kwargs.get("id", "")).strip()
        if not job_id:
            return ToolResult.error(name=self.name, content="cron_error: id is required for cancel")
        job = self._scheduler.cancel(job_id)
        if job is None:
            return ToolResult.error(name=self.name, content=f"cron_error: job not found: {job_id}")
        return ToolResult.ok(
            name=self.name,
            content=f"cron_cancelled: {job.id}",
            structured_content={"id": job.id, "enabled": job.enabled},
        )
