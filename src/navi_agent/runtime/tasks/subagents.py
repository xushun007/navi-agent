from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from ..models import RuntimeResult

if TYPE_CHECKING:
    from ..agent.control import RunCancellationToken


SUBAGENT_SYSTEM_PROMPT = """You are an isolated Navi Agent worker.

Complete only the delegated task. You do not have the parent conversation, so rely on the goal and context provided below. Use tools when needed. Return a concise, self-contained report containing findings, evidence, files changed, validation performed, and unresolved blockers. Do not ask the user questions and do not delegate further.
"""

DEFAULT_SUBAGENT_TOOLSETS = ("file", "skills")
ALLOWED_SUBAGENT_TOOLSETS = frozenset({"file", "terminal", "code", "skills"})
MAX_CONCURRENT_SUBAGENTS = 3
DEFAULT_SUBAGENT_DEADLINE_SECONDS = 300.0


class SubagentRuntime(Protocol):
    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
        source: str = "console",
        cancellation_token: RunCancellationToken | None = None,
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


@dataclass(slots=True)
class _PreparedRun:
    task: SubagentTask
    session_id: str
    toolsets: tuple[str, ...]
    cancellation_token: RunCancellationToken


class SubagentService:
    def __init__(
        self,
        runtime_factory: SubagentRuntimeFactory,
        deadline_seconds: float = DEFAULT_SUBAGENT_DEADLINE_SECONDS,
    ) -> None:
        if deadline_seconds <= 0:
            raise ValueError("subagent deadline must be positive")
        self._runtime_factory = runtime_factory
        self._deadline_seconds = deadline_seconds

    def run(
        self,
        *,
        goal: str,
        context: str,
        parent_session_id: str,
        user_id: str,
        toolsets: list[str] | None = None,
        non_interactive: bool = False,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> SubagentRun:
        prepared = self._prepare(
            SubagentTask(goal, context, toolsets),
            parent_session_id=parent_session_id,
        )
        return self._execute(
            [prepared],
            parent_session_id=parent_session_id,
            user_id=user_id,
            non_interactive=non_interactive,
            cancellation_requested=cancellation_requested,
        )[0]

    def run_many(
        self,
        *,
        tasks: list[SubagentTask],
        parent_session_id: str,
        user_id: str,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> list[SubagentRun]:
        if not tasks:
            raise ValueError("at least one subagent task is required")
        if len(tasks) > MAX_CONCURRENT_SUBAGENTS:
            raise ValueError(
                f"subagent batch exceeds maximum of {MAX_CONCURRENT_SUBAGENTS} tasks"
            )
        prepared = [
            self._prepare(task, parent_session_id=parent_session_id) for task in tasks
        ]
        return self._execute(
            prepared,
            parent_session_id=parent_session_id,
            user_id=user_id,
            non_interactive=True,
            cancellation_requested=cancellation_requested,
        )

    def _execute(
        self,
        prepared: list[_PreparedRun],
        *,
        parent_session_id: str,
        user_id: str,
        non_interactive: bool,
        cancellation_requested: Callable[[], bool] | None,
    ) -> list[SubagentRun]:
        executor = ThreadPoolExecutor(len(prepared), thread_name_prefix="navi-subagent")
        futures = [
            executor.submit(
                self._run_one,
                item,
                parent_session_id,
                user_id,
                non_interactive,
            )
            for item in prepared
        ]
        pending = set(futures)
        deadline = monotonic() + self._deadline_seconds
        status = "timed_out"
        try:
            while pending:
                if cancellation_requested is not None and cancellation_requested():
                    status = "cancelled"
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                _, pending = wait(
                    pending,
                    timeout=min(0.05, remaining),
                    return_when=FIRST_COMPLETED,
                )
            unfinished = set(pending)
            for item, future in zip(prepared, futures, strict=True):
                if future in unfinished:
                    item.cancellation_token.cancel(
                        "parent_cancelled" if status == "cancelled" else "deadline_exceeded"
                    )
                    future.cancel()
            message = "Subagent cancelled" if status == "cancelled" else "Subagent timed out"
            return [
                future.result()
                if future not in unfinished
                else SubagentRun(item.session_id, status, message, item.toolsets)
                for item, future in zip(prepared, futures, strict=True)
            ]
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_one(
        self,
        prepared: _PreparedRun,
        parent_session_id: str,
        user_id: str,
        non_interactive: bool,
    ) -> SubagentRun:
        runtime = self._runtime_factory(
            list(prepared.toolsets), parent_session_id, non_interactive
        )
        result = runtime.run_conversation(
            session_id=prepared.session_id,
            user_id=user_id,
            user_message=self._build_task_prompt(
                goal=prepared.task.goal,
                context=prepared.task.context,
            ),
            system_prompt=SUBAGENT_SYSTEM_PROMPT,
            source="subagent",
            cancellation_token=prepared.cancellation_token,
        )
        return SubagentRun(
            prepared.session_id,
            result.status,
            result.final_response,
            prepared.toolsets,
        )

    def _prepare(self, task: SubagentTask, *, parent_session_id: str) -> _PreparedRun:
        from ..agent.control import RunCancellationToken

        goal = task.goal.strip()
        if not goal:
            raise ValueError("goal is required")
        task = SubagentTask(goal, task.context, task.toolsets)
        return _PreparedRun(
            task,
            f"{parent_session_id}:subagent:{uuid4().hex[:12]}",
            self._normalize_toolsets(task.toolsets),
            RunCancellationToken(),
        )

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
