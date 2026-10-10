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
StopAction = Literal["allow", "follow_up", "block"]


@dataclass(frozen=True, slots=True)
class StopDecision:
    """Decision made when the model returns without tool calls."""

    action: StopAction
    message: str = ""

    @classmethod
    def allow(cls) -> "StopDecision":
        return cls(action="allow")

    @classmethod
    def follow_up(cls, message: str) -> "StopDecision":
        if not message.strip():
            raise ValueError("stop follow-up message must not be empty")
        return cls(action="follow_up", message=message)

    @classmethod
    def block(cls, message: str = "") -> "StopDecision":
        return cls(action="block", message=message)


@dataclass(frozen=True, slots=True)
class AgentLoopOutcome:
    """Outcome of the step loop that executes within one runtime turn."""

    status: AgentLoopStatus
    iteration: int
    invocation: ModelInvocation | None = None
    pending_result: ToolResult | None = None
    error: Exception | None = None

    @property
    def step_number(self) -> int:
        """Semantic alias for the compatibility ``iteration`` field."""
        return self.iteration


class AgentLoop:
    """Own the model/tool step loop within one runtime turn."""

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
        stop_hook: Callable[[int, ModelInvocation], StopDecision] | None = None,
        on_stop_follow_up: Callable[[int, StopDecision], None] | None = None,
        max_stop_follow_ups: int = 2,
    ) -> AgentLoopOutcome:
        if max_stop_follow_ups < 0:
            raise ValueError("max_stop_follow_ups must be non-negative")
        stop_follow_ups = 0
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
                decision = stop_hook(iteration, invocation) if stop_hook else StopDecision.allow()
                if decision.action != "allow" and stop_follow_ups < max_stop_follow_ups:
                    stop_follow_ups += 1
                    if on_stop_follow_up is not None:
                        on_stop_follow_up(iteration, decision)
                    continue
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
