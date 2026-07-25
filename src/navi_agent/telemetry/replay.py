from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from navi_agent.events import RuntimeEvent

from .trajectory import RuntimeTrajectory


class ReplayPlanError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ReplayToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayModelOutput:
    content: str
    reasoning_content: str | None
    tool_calls: tuple[ReplayToolCall, ...]
    provider: str | None
    model: str | None
    usage: ReplayUsage


@dataclass(frozen=True, slots=True)
class ReplayToolOutput:
    tool_call_id: str
    name: str
    content: str
    status: str
    metadata: dict[str, Any]
    structured_content: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayModelStep:
    iteration: int
    purpose: str
    response: ReplayModelOutput


@dataclass(frozen=True, slots=True)
class ReplayToolStep:
    iteration: int
    call: ReplayToolCall
    result: ReplayToolOutput


@dataclass(frozen=True, slots=True)
class RuntimeReplayPlan:
    source_session_id: str
    source_run_id: str
    user_id: str
    user_message: str
    system_prompt: str | None
    expected_status: str
    expected_final_response: str
    model_steps: tuple[ReplayModelStep, ...]
    tool_steps: tuple[ReplayToolStep, ...]

    @property
    def agent_model_steps(self) -> tuple[ReplayModelStep, ...]:
        return tuple(step for step in self.model_steps if step.purpose == "agent")


class RuntimeReplayPlanner:
    """Builds a deterministic offline replay script from one complete run."""

    def build(self, trajectory: RuntimeTrajectory) -> RuntimeReplayPlan:
        events = self._validate_trajectory(trajectory)
        started = self._exactly_one(events, "runtime.started")
        user_message = self._exactly_one(events, "user.message")
        completed = self._exactly_one(events, "runtime.completed")
        context_ready = self._optional_one(events, "runtime.context_ready")

        if completed.metadata.get("trajectory_complete") is False:
            raise ReplayPlanError("runtime trajectory is marked incomplete")

        return RuntimeReplayPlan(
            source_session_id=started.session_id,
            source_run_id=started.run_id,
            user_id=started.user_id,
            user_message=_required_string(user_message.metadata, "content"),
            system_prompt=(
                _optional_string(context_ready.metadata, "system_prompt")
                if context_ready is not None
                else None
            ),
            expected_status=_required_string(completed.metadata, "status"),
            expected_final_response=_optional_string(
                completed.metadata,
                "final_response",
            )
            or "",
            model_steps=tuple(
                self._model_step(event)
                for event in events
                if event.name == "model.response"
            ),
            tool_steps=tuple(
                self._tool_step(event)
                for event in events
                if event.name == "tool.result"
            ),
        )

    @staticmethod
    def _validate_trajectory(trajectory: RuntimeTrajectory) -> list[RuntimeEvent]:
        if trajectory.empty:
            raise ReplayPlanError("runtime trajectory is empty")

        events = sorted(trajectory.events, key=lambda event: event.sequence)
        session_ids = {event.session_id for event in events}
        run_ids = {event.run_id for event in events}
        user_ids = {event.user_id for event in events}
        if len(session_ids) != 1 or len(run_ids) != 1 or len(user_ids) != 1:
            raise ReplayPlanError("runtime trajectory must contain exactly one run")
        if trajectory.session_id not in session_ids:
            raise ReplayPlanError("trajectory session_id does not match its events")
        if trajectory.run_id is not None and trajectory.run_id not in run_ids:
            raise ReplayPlanError("trajectory run_id does not match its events")

        sequences = [event.sequence for event in events]
        if len(sequences) != len(set(sequences)):
            raise ReplayPlanError("runtime trajectory contains duplicate event sequences")
        return events

    @staticmethod
    def _exactly_one(events: list[RuntimeEvent], name: str) -> RuntimeEvent:
        matches = [event for event in events if event.name == name]
        if len(matches) != 1:
            raise ReplayPlanError(f"runtime trajectory requires exactly one {name} event")
        return matches[0]

    @staticmethod
    def _optional_one(events: list[RuntimeEvent], name: str) -> RuntimeEvent | None:
        matches = [event for event in events if event.name == name]
        if len(matches) > 1:
            raise ReplayPlanError(f"runtime trajectory contains multiple {name} events")
        return matches[0] if matches else None

    @staticmethod
    def _model_step(event: RuntimeEvent) -> ReplayModelStep:
        metadata = event.metadata
        usage = _mapping(metadata.get("usage"))
        return ReplayModelStep(
            iteration=event.iteration or 0,
            purpose=_optional_string(metadata, "purpose") or "agent",
            response=ReplayModelOutput(
                content=_optional_string(metadata, "content") or "",
                reasoning_content=_optional_string(metadata, "reasoning_content"),
                tool_calls=tuple(
                    ReplayToolCall(
                        id=_required_string(item, "id"),
                        name=_required_string(item, "name"),
                        arguments=_mapping(item.get("arguments")),
                    )
                    for item in _mapping_list(metadata.get("tool_calls"))
                ),
                provider=_optional_string(metadata, "provider"),
                model=_optional_string(metadata, "model"),
                usage=ReplayUsage(
                    input_tokens=_integer(usage.get("input_tokens")),
                    output_tokens=_integer(usage.get("output_tokens")),
                    cache_read_tokens=_integer(usage.get("cache_read_tokens")),
                    cache_write_tokens=_integer(usage.get("cache_write_tokens")),
                    reasoning_tokens=_integer(usage.get("reasoning_tokens")),
                    cost_usd=_number(usage.get("cost_usd")),
                ),
            ),
        )

    @staticmethod
    def _tool_step(event: RuntimeEvent) -> ReplayToolStep:
        metadata = event.metadata
        tool_call_id = _required_string(metadata, "tool_call_id")
        tool_name = _required_string(metadata, "tool_name")
        arguments = _mapping(metadata.get("arguments"))
        return ReplayToolStep(
            iteration=event.iteration or 0,
            call=ReplayToolCall(
                id=tool_call_id,
                name=tool_name,
                arguments=arguments,
            ),
            result=ReplayToolOutput(
                tool_call_id=tool_call_id,
                name=tool_name,
                content=_optional_string(metadata, "content") or "",
                status=_optional_string(metadata, "status") or "error",
                metadata=_mapping(metadata.get("metadata")),
                structured_content=_mapping(metadata.get("structured_content")),
            ),
        )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ReplayPlanError(f"runtime event field {key} must be a non-empty string")
    return value


def _optional_string(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) else None


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
