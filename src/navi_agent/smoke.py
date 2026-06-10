from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from navi_agent.app import AppRequest, ApplicationService


@dataclass(frozen=True, slots=True)
class SmokeTask:
    name: str
    description: str
    prompt: str


SMOKE_TASKS: dict[str, SmokeTask] = {
    "readme-summary": SmokeTask(
        name="readme-summary",
        description="Read the project README and summarize the current product goal.",
        prompt="阅读 README.md，简要总结这个项目的目标、当前范围和后续方向。",
    ),
    "runtime-trace-check": SmokeTask(
        name="runtime-trace-check",
        description="Inspect runtime and telemetry code, then summarize the trace flow.",
        prompt="检查 src/navi_agent/runtime 和 src/navi_agent/telemetry，说明一次运行的 trace 是如何被记录和导出的。",
    ),
    "config-check": SmokeTask(
        name="config-check",
        description="Inspect config.example.yaml and explain the minimum required configuration.",
        prompt="读取 config.example.yaml，说明运行这个 agent 最少需要配置哪些字段。",
    ),
    "workspace-search": SmokeTask(
        name="workspace-search",
        description="Use file search tools to locate the main CLI and runtime entrypoints.",
        prompt="定位这个项目的 CLI 入口、应用入口和 runtime 入口，并简要说明它们的关系。",
    ),
}


def list_smoke_tasks() -> list[SmokeTask]:
    return [SMOKE_TASKS[name] for name in sorted(SMOKE_TASKS)]


def get_smoke_task(name: str) -> SmokeTask:
    try:
        return SMOKE_TASKS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown smoke task: {name}") from exc


def run_smoke_task(
    *,
    app: ApplicationService,
    task_name: str,
    user_id: str,
    session_id: str | None = None,
    system_prompt: str | None = None,
):
    task = get_smoke_task(task_name)
    return app.handle(
        AppRequest(
            user_id=user_id,
            session_id=session_id or f"smoke-{task.name}-{uuid4().hex[:8]}",
            message=task.prompt,
            system_prompt=system_prompt,
        )
    )
