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
class _MemoryNudgeState:
    turns_since_memory: int = 0
    observed_trace_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _SkillNudgeState:
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
        self._memory_states: dict[str, _MemoryNudgeState] = {}
        self._skill_states: dict[tuple[str, str], _SkillNudgeState] = {}
        self._active_key: tuple[str, str] | None = None

    @property
    def turns_since_memory(self) -> int:
        if self._active_key is None:
            return 0
        return self._memory_state(self._active_key[0]).turns_since_memory

    @property
    def tool_executions_since_skill(self) -> int:
        return self._active_skill_state().tool_executions_since_skill

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
            session_id = session_id or traces[-1].session_id
            user_id = user_id or traces[-1].user_id
        key = (user_id, session_id)
        self._active_key = key
        if user_id not in self._memory_states:
            memory_state = self._memory_state(user_id)
            for trace in traces:
                if trace.user_id == user_id:
                    self._observe_memory(
                        memory_state,
                        trace,
                        memory_available=memory_available,
                    )
            self._consume_memory_watermark(memory_state)
        if key not in self._skill_states:
            skill_state = self._skill_state(key)
            for trace in traces:
                if trace.user_id == user_id and trace.session_id == session_id:
                    self._observe_skill(
                        skill_state,
                        trace,
                        skill_available=skill_available,
                    )
            self._consume_skill_watermark(skill_state)

    def decide(
        self,
        trace: RuntimeTrace,
        *,
        memory_available: bool = True,
        skill_available: bool = True,
    ) -> ReviewTriggerDecision:
        self._active_key = (trace.user_id, trace.session_id)
        memory_state = self._memory_state(trace.user_id)
        skill_state = self._skill_state(self._active_key)
        self._observe_memory(
            memory_state,
            trace,
            memory_available=memory_available,
        )
        self._observe_skill(
            skill_state,
            trace,
            skill_available=skill_available,
        )
        reasons: list[str] = []
        review_memory = (
            memory_available
            and self._memory_turn_interval > 0
            and memory_state.turns_since_memory >= self._memory_turn_interval
        )
        review_skill = (
            skill_available
            and self._skill_tool_interval > 0
            and skill_state.tool_executions_since_skill >= self._skill_tool_interval
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
        self._active_key = (trace.user_id, trace.session_id)
        if decision.review_memory and self._memory_turn_interval > 0:
            memory_state = self._memory_state(trace.user_id)
            memory_state.turns_since_memory = max(
                0,
                memory_state.turns_since_memory - self._memory_turn_interval,
            )
        if decision.review_skill and self._skill_tool_interval > 0:
            skill_state = self._skill_state(self._active_key)
            skill_state.tool_executions_since_skill = max(
                0,
                skill_state.tool_executions_since_skill - self._skill_tool_interval,
            )

    def reset_skill(self, trace: RuntimeTrace) -> None:
        self._active_key = (trace.user_id, trace.session_id)
        self._skill_state(self._active_key).tool_executions_since_skill = 0

    def _observe_memory(
        self,
        state: _MemoryNudgeState,
        trace: RuntimeTrace,
        *,
        memory_available: bool,
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

    def _observe_skill(
        self,
        state: _SkillNudgeState,
        trace: RuntimeTrace,
        *,
        skill_available: bool,
    ) -> None:
        if trace.trace_id in state.observed_trace_ids:
            return
        state.observed_trace_ids.add(trace.trace_id)
        if trace.status != "success" or not trace.final_response.strip():
            return
        if _has_successful_skill_write(trace, self._SKILL_WRITE_ACTIONS):
            state.tool_executions_since_skill = 0
        elif skill_available and self._skill_tool_interval > 0:
            state.tool_executions_since_skill += len(trace.tool_executions)

    def _consume_memory_watermark(self, state: _MemoryNudgeState) -> None:
        if self._memory_turn_interval > 0:
            state.turns_since_memory %= self._memory_turn_interval

    def _consume_skill_watermark(self, state: _SkillNudgeState) -> None:
        if self._skill_tool_interval > 0:
            state.tool_executions_since_skill %= self._skill_tool_interval

    def _memory_state(self, user_id: str) -> _MemoryNudgeState:
        return self._memory_states.setdefault(user_id, _MemoryNudgeState())

    def _skill_state(self, key: tuple[str, str]) -> _SkillNudgeState:
        return self._skill_states.setdefault(key, _SkillNudgeState())

    def _active_skill_state(self) -> _SkillNudgeState:
        if self._active_key is None:
            return _SkillNudgeState()
        return self._skill_state(self._active_key)


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
