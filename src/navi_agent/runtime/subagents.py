from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from .models import RuntimeResult


SUBAGENT_SYSTEM_PROMPT = """You are an isolated Navi Agent worker.

Complete only the delegated task. You do not have the parent conversation, so rely on the goal and context provided below. Use tools when needed. Return a concise, self-contained report containing findings, evidence, files changed, validation performed, and unresolved blockers. Do not ask the user questions and do not delegate further.
"""

DEFAULT_SUBAGENT_TOOLSETS = ("file", "skills")
ALLOWED_SUBAGENT_TOOLSETS = frozenset({"file", "terminal", "code", "skills"})
MAX_CONCURRENT_SUBAGENTS = 3


class SubagentRuntime(Protocol):
    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> RuntimeResult: ...


class SubagentRuntimeFactory(Protocol):
    def __call__(
        self,
        enabled_toolsets: list[str],
        parent_session_id: str,
        non_interactive: bool,
    ) -> SubagentRuntime: ...


@dataclass(slots=True)
class SubagentTask:
    goal: str
    context: str
    toolsets: list[str] | None = None


@dataclass(slots=True)
class SubagentRun:
    session_id: str
    status: str
    final_response: str
    toolsets: tuple[str, ...]


class SubagentService:
    def __init__(self, runtime_factory: SubagentRuntimeFactory) -> None:
        self._runtime_factory = runtime_factory

    def run(
        self,
        *,
        goal: str,
        context: str,
        parent_session_id: str,
        user_id: str,
        toolsets: list[str] | None = None,
        non_interactive: bool = False,
    ) -> SubagentRun:
        normalized_goal = goal.strip()
        if not normalized_goal:
            raise ValueError("goal is required")

        selected_toolsets = self._normalize_toolsets(toolsets)
        child_session_id = f"{parent_session_id}:subagent:{uuid4().hex[:12]}"
        runtime = self._runtime_factory(
            list(selected_toolsets),
            parent_session_id,
            non_interactive,
        )
        result = runtime.run_conversation(
            session_id=child_session_id,
            user_id=user_id,
            user_message=self._build_task_prompt(goal=normalized_goal, context=context),
            system_prompt=SUBAGENT_SYSTEM_PROMPT,
        )
        return SubagentRun(
            session_id=child_session_id,
            status=result.status,
            final_response=result.final_response,
            toolsets=selected_toolsets,
        )

    def run_many(
        self,
        *,
        tasks: list[SubagentTask],
        parent_session_id: str,
        user_id: str,
    ) -> list[SubagentRun]:
        if not tasks:
            raise ValueError("at least one subagent task is required")
        if len(tasks) > MAX_CONCURRENT_SUBAGENTS:
            raise ValueError(
                f"subagent batch exceeds maximum of {MAX_CONCURRENT_SUBAGENTS} tasks"
            )

        with ThreadPoolExecutor(
            max_workers=len(tasks),
            thread_name_prefix="navi-subagent",
        ) as executor:
            futures = [
                executor.submit(
                    self.run,
                    goal=task.goal,
                    context=task.context,
                    parent_session_id=parent_session_id,
                    user_id=user_id,
                    toolsets=task.toolsets,
                    non_interactive=True,
                )
                for task in tasks
            ]
            return [future.result() for future in futures]

    @staticmethod
    def _normalize_toolsets(toolsets: list[str] | None) -> tuple[str, ...]:
        requested = toolsets or list(DEFAULT_SUBAGENT_TOOLSETS)
        normalized = tuple(
            dict.fromkeys(str(item).strip() for item in requested if str(item).strip())
        )
        unsupported = sorted(set(normalized) - ALLOWED_SUBAGENT_TOOLSETS)
        if unsupported:
            raise ValueError(f"unsupported subagent toolsets: {', '.join(unsupported)}")
        if not normalized:
            raise ValueError("at least one subagent toolset is required")
        return normalized

    @staticmethod
    def _build_task_prompt(*, goal: str, context: str) -> str:
        normalized_context = context.strip() or "No additional context was provided."
        return "\n".join(
            [
                "# Delegated Goal",
                goal,
                "",
                "# Context From Parent",
                normalized_context,
                "",
                "# Output Contract",
                "Return only the final self-contained report for the parent agent.",
            ]
        )
