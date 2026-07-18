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
    def decide(self, trace: RuntimeTrace) -> ReviewTriggerDecision: ...


class NudgeReviewTriggerPolicy:
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
        self._turns_since_memory = 0
        self._tool_executions_since_skill = 0

    @property
    def turns_since_memory(self) -> int:
        return self._turns_since_memory

    @property
    def tool_executions_since_skill(self) -> int:
        return self._tool_executions_since_skill

    def decide(self, trace: RuntimeTrace) -> ReviewTriggerDecision:
        if trace.status != "success" or not trace.final_response.strip():
            return ReviewTriggerDecision()

        reasons: list[str] = []
        review_memory = False
        review_skill = False

        if self._memory_turn_interval > 0:
            self._turns_since_memory += 1
            if self._turns_since_memory >= self._memory_turn_interval:
                review_memory = True
                reasons.append("memory_nudge_counter")
                self._turns_since_memory = 0

        if self._skill_tool_interval > 0 and trace.tool_executions:
            self._tool_executions_since_skill += len(trace.tool_executions)
            if self._tool_executions_since_skill >= self._skill_tool_interval:
                review_skill = True
                reasons.append("skill_nudge_counter")
                self._tool_executions_since_skill = 0

        return ReviewTriggerDecision(
            review_memory=review_memory,
            review_skill=review_skill,
            reasons=reasons,
        )
