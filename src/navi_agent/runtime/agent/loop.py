from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from navi_agent.tooling import ToolResult

from .control import RunCancelledError
from .model_invoker import ModelInvocation

AgentLoopStatus = Literal[
    "completed",
    "cancelled",
    "failed",
    "waiting",
    "iteration_limit",
]


@dataclass(frozen=True, slots=True)
class AgentLoopOutcome:
    status: AgentLoopStatus
    iteration: int
    invocation: ModelInvocation | None = None
    pending_result: ToolResult | None = None
    error: Exception | None = None


class AgentLoop:
    """Own the model/tool iteration state machine and nothing around it."""

    def __init__(self, max_iterations: int) -> None:
        self._max_iterations = max_iterations

    def run(
        self,
        *,
        is_cancelled: Callable[[], bool],
        on_iteration_started: Callable[[int], None],
        invoke_model: Callable[[int], ModelInvocation],
        on_model_response: Callable[[int, ModelInvocation, bool], None],
        execute_tools: Callable[[int, ModelInvocation], ToolResult | None],
    ) -> AgentLoopOutcome:
        for iteration in range(1, self._max_iterations + 1):
            if is_cancelled():
                return AgentLoopOutcome(status="cancelled", iteration=iteration - 1)

            on_iteration_started(iteration)
            try:
                invocation = invoke_model(iteration)
            except RunCancelledError:
                return AgentLoopOutcome(status="cancelled", iteration=iteration)
            except Exception as exc:
                return AgentLoopOutcome(status="failed", iteration=iteration, error=exc)

            discarded = is_cancelled()
            on_model_response(iteration, invocation, discarded)
            if discarded:
                return AgentLoopOutcome(
                    status="cancelled",
                    iteration=iteration,
                    invocation=invocation,
                )
            if not invocation.response.tool_calls:
                return AgentLoopOutcome(
                    status="completed",
                    iteration=iteration,
                    invocation=invocation,
                )

            pending_result = execute_tools(iteration, invocation)
            if is_cancelled():
                return AgentLoopOutcome(
                    status="cancelled",
                    iteration=iteration,
                    invocation=invocation,
                )
            if pending_result is not None:
                return AgentLoopOutcome(
                    status="waiting",
                    iteration=iteration,
                    invocation=invocation,
                    pending_result=pending_result,
                )

        return AgentLoopOutcome(
            status="iteration_limit",
            iteration=self._max_iterations,
        )
