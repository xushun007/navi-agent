from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from navi_agent.telemetry import RuntimeTrace


@dataclass(frozen=True, slots=True)
class ReviewTriggerDecision:
    review_memory: bool = False
    review_skill: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def should_review(self) -> bool:
        return self.review_memory or self.review_skill


class ReviewTriggerPolicy(Protocol):
    def decide(
        self,
        trace: RuntimeTrace,
        *,
        memory_available: bool = True,
        skill_available: bool = True,
    ) -> ReviewTriggerDecision: ...

    def acknowledge(
        self,
        trace: RuntimeTrace,
        decision: ReviewTriggerDecision,
    ) -> None: ...

    def reset_skill(self, trace: RuntimeTrace) -> None: ...


@dataclass(slots=True)
class _NudgeState:
    turns_since_memory: int = 0
    tool_executions_since_skill: int = 0
    observed_trace_ids: set[str] = field(default_factory=set)


class NudgeReviewTriggerPolicy:
    _SKILL_WRITE_ACTIONS = {
        "create",
        "append",
        "write_attachment",
        "draft_create",
        "draft_append",
        "draft_attachment",
    }

    def __init__(
        self,
        *,
        memory_turn_interval: int = 10,
        skill_tool_interval: int = 10,
    ) -> None:
        if memory_turn_interval < 0:
            raise ValueError("memory_turn_interval must be non-negative")
        if skill_tool_interval < 0:
            raise ValueError("skill_tool_interval must be non-negative")
        self._memory_turn_interval = memory_turn_interval
        self._skill_tool_interval = skill_tool_interval
        self._states: dict[tuple[str, str], _NudgeState] = {}
        self._active_key: tuple[str, str] | None = None

    @property
    def turns_since_memory(self) -> int:
        return self._active_state().turns_since_memory

    @property
    def tool_executions_since_skill(self) -> int:
        return self._active_state().tool_executions_since_skill

    def hydrate(
        self,
        traces: list[RuntimeTrace],
        *,
        session_id: str = "",
        user_id: str = "",
        memory_available: bool = True,
        skill_available: bool = True,
    ) -> None:
        if traces:
            session_id = traces[-1].session_id
            user_id = traces[-1].user_id
        key = (user_id, session_id)
        self._active_key = key
        if key in self._states:
            return
        state = _NudgeState()
        self._states[key] = state
        for trace in traces:
            self._observe(
                state,
                trace,
                memory_available=memory_available,
                skill_available=skill_available,
            )
            self._consume_historical_watermarks(state)

    def decide(
        self,
        trace: RuntimeTrace,
        *,
        memory_available: bool = True,
        skill_available: bool = True,
    ) -> ReviewTriggerDecision:
        state = self._state_for(trace)
        self._observe(
            state,
            trace,
            memory_available=memory_available,
            skill_available=skill_available,
        )
        reasons: list[str] = []
        review_memory = (
            memory_available
            and self._memory_turn_interval > 0
            and state.turns_since_memory >= self._memory_turn_interval
        )
        review_skill = (
            skill_available
            and self._skill_tool_interval > 0
            and state.tool_executions_since_skill >= self._skill_tool_interval
        )
        if review_memory:
            reasons.append("memory_nudge_counter")
        if review_skill:
            reasons.append("skill_nudge_counter")
        return ReviewTriggerDecision(
            review_memory=review_memory,
            review_skill=review_skill,
            reasons=reasons,
        )

    def acknowledge(
        self,
        trace: RuntimeTrace,
        decision: ReviewTriggerDecision,
    ) -> None:
        state = self._state_for(trace)
        if decision.review_memory and self._memory_turn_interval > 0:
            state.turns_since_memory = max(
                0,
                state.turns_since_memory - self._memory_turn_interval,
            )
        if decision.review_skill and self._skill_tool_interval > 0:
            state.tool_executions_since_skill = max(
                0,
                state.tool_executions_since_skill - self._skill_tool_interval,
            )

    def reset_skill(self, trace: RuntimeTrace) -> None:
        self._state_for(trace).tool_executions_since_skill = 0

    def _observe(
        self,
        state: _NudgeState,
        trace: RuntimeTrace,
        *,
        memory_available: bool,
        skill_available: bool,
    ) -> None:
        if trace.trace_id in state.observed_trace_ids:
            return
        state.observed_trace_ids.add(trace.trace_id)
        if trace.status != "success" or not trace.final_response.strip():
            return

        if _has_successful_tool_execution(trace, "memory"):
            state.turns_since_memory = 0
        elif memory_available and self._memory_turn_interval > 0:
            state.turns_since_memory += 1

        if _has_successful_skill_write(trace, self._SKILL_WRITE_ACTIONS):
            state.tool_executions_since_skill = 0
        elif skill_available and self._skill_tool_interval > 0:
            state.tool_executions_since_skill += len(trace.tool_executions)

    def _consume_historical_watermarks(self, state: _NudgeState) -> None:
        if self._memory_turn_interval > 0:
            state.turns_since_memory %= self._memory_turn_interval
        if self._skill_tool_interval > 0:
            state.tool_executions_since_skill %= self._skill_tool_interval

    def _state_for(self, trace: RuntimeTrace) -> _NudgeState:
        key = (trace.user_id, trace.session_id)
        self._active_key = key
        return self._states.setdefault(key, _NudgeState())

    def _active_state(self) -> _NudgeState:
        if self._active_key is None:
            return _NudgeState()
        return self._states[self._active_key]


def _has_successful_tool_execution(trace: RuntimeTrace, tool_name: str) -> bool:
    return any(
        execution.tool_name == tool_name and execution.status == "success"
        for execution in trace.tool_executions
    )


def _has_successful_skill_write(
    trace: RuntimeTrace,
    write_actions: set[str],
) -> bool:
    return any(
        execution.tool_name == "skill_manage"
        and execution.status == "success"
        and str(execution.arguments.get("action") or "") in write_actions
        for execution in trace.tool_executions
    )
