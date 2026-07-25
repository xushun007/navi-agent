from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from navi_agent.telemetry import (
    ReplayModelFailure,
    ReplayModelOutput,
    ReplayModelStep,
    ReplayToolStep,
    RuntimeEventStore,
    RuntimeReplayPlan,
    RuntimeReplayPlanner,
    RuntimeTrajectoryService,
)
from navi_agent.tooling import ToolContext, ToolResult

from .agent.context import ContextEngine
from .agent.engine import AgentRuntime
from .models import ModelResponse, ModelUsage, RuntimeMode, RuntimeResult, ToolCall
from .sessions.memory import InMemorySessionStore
from .transports.base import ModelRequest


@dataclass(frozen=True, slots=True)
class ReplayDivergence:
    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class OfflineReplayResult:
    source_run_id: str
    replay_run_id: str
    runtime_result: RuntimeResult
    divergences: tuple[ReplayDivergence, ...]

    @property
    def verified(self) -> bool:
        return not self.divergences


class OfflineRuntimeReplay:
    """Replays recorded decisions through AgentRuntime without external effects."""

    def execute(self, plan: RuntimeReplayPlan) -> OfflineReplayResult:
        transport = _RecordedModelTransport(
            list(plan.agent_model_steps)
        )
        tool_registry = _RecordedToolRegistry(
            list(plan.tool_steps)
        )
        max_iterations = max(
            (step.iteration for step in plan.agent_model_steps),
            default=1,
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=tool_registry,
            session_store=InMemorySessionStore(),
            context_engine=ContextEngine(
                context_limit_tokens=10_000_000,
                reserved_output_tokens=0,
            ),
            max_iterations=max_iterations,
        )

        result = runtime.run_conversation(
            session_id=f"{plan.source_session_id}:offline-replay",
            user_id=plan.user_id,
            user_message=plan.user_message,
            system_prompt=plan.system_prompt,
            source="replay",
            mode=RuntimeMode.REPLAY,
        )
        divergences = [
            *transport.divergences,
            *tool_registry.divergences,
        ]
        if result.status != plan.expected_status:
            divergences.append(
                ReplayDivergence(
                    kind="status",
                    message=(
                        f"expected runtime status {plan.expected_status!r}, "
                        f"got {result.status!r}"
                    ),
                )
            )
        if result.final_response != plan.expected_final_response:
            divergences.append(
                ReplayDivergence(
                    kind="final_response",
                    message="replayed final response differs from the recorded run",
                )
            )
        if transport.remaining:
            divergences.append(
                ReplayDivergence(
                    kind="model_steps",
                    message=f"{transport.remaining} recorded model step(s) were not consumed",
                )
            )
        if tool_registry.remaining:
            divergences.append(
                ReplayDivergence(
                    kind="tool_steps",
                    message=f"{tool_registry.remaining} recorded tool result(s) were not consumed",
                )
            )
        return OfflineReplayResult(
            source_run_id=plan.source_run_id,
            replay_run_id=result.run_id,
            runtime_result=result,
            divergences=tuple(divergences),
        )


class OfflineReplayService:
    def __init__(self, event_store: RuntimeEventStore) -> None:
        self._trajectory_service = RuntimeTrajectoryService(event_store)
        self._planner = RuntimeReplayPlanner()
        self._replay = OfflineRuntimeReplay()

    def replay(self, *, session_id: str, run_id: str) -> OfflineReplayResult:
        trajectory = self._trajectory_service.load(
            session_id=session_id,
            run_id=run_id,
        )
        return self._replay.execute(self._planner.build(trajectory))


class _RecordedModelTransport:
    def __init__(self, steps: list[ReplayModelStep]) -> None:
        self._steps = list(steps)
        self._index = 0
        self.divergences: list[ReplayDivergence] = []

    @property
    def remaining(self) -> int:
        return len(self._steps) - self._index

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._index >= len(self._steps):
            self.divergences.append(
                ReplayDivergence(
                    kind="model_steps",
                    message="runtime requested more model calls than were recorded",
                )
            )
            return ModelResponse(content="")
        step = self._steps[self._index]
        self._index += 1
        if step.failure is not None:
            raise _recorded_exception(step.failure)
        if step.response is None:
            raise RuntimeError("recorded model step has no response or failure")
        return _model_response(step.response)


class _RecordedToolRegistry:
    def __init__(self, steps: list[ReplayToolStep]) -> None:
        self._steps = {step.call.id: step for step in steps}
        self._consumed: set[str] = set()
        self.divergences: list[ReplayDivergence] = []

    @property
    def remaining(self) -> int:
        return len(self._steps) - len(self._consumed)

    def schemas(
        self,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": "Recorded offline replay tool",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            }
            for name in sorted({step.call.name for step in self._steps.values()})
        ]

    def dispatch(
        self,
        tool_calls: list[ToolCall],
        context: ToolContext | None = None,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> list[ToolResult]:
        return [self._result_for(tool_call) for tool_call in tool_calls]

    def dispatch_approved(
        self,
        tool_call: ToolCall,
        context: ToolContext | None = None,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> ToolResult:
        return self._result_for(tool_call)

    def _result_for(self, tool_call: ToolCall) -> ToolResult:
        step = self._steps.get(tool_call.id)
        if step is None:
            self.divergences.append(
                ReplayDivergence(
                    kind="tool_steps",
                    message=f"no recorded result exists for tool call {tool_call.id}",
                )
            )
            return ToolResult.error(
                name=tool_call.name,
                content="Offline replay has no recorded tool result.",
            ).bind(tool_call.id)
        self._consumed.add(tool_call.id)
        if step.call.name != tool_call.name:
            self.divergences.append(
                ReplayDivergence(
                    kind="tool_name",
                    message=(
                        f"recorded tool {step.call.name!r} does not match "
                        f"requested tool {tool_call.name!r}"
                    ),
                )
            )
        if step.call.arguments != tool_call.arguments:
            self.divergences.append(
                ReplayDivergence(
                    kind="tool_arguments",
                    message=f"tool arguments differ for call {tool_call.id}",
                )
            )
        return _tool_result(step)


def _model_response(output: ReplayModelOutput) -> ModelResponse:
    return ModelResponse(
        content=output.content,
        reasoning_content=output.reasoning_content,
        tool_calls=[
            ToolCall(
                id=tool_call.id,
                name=tool_call.name,
                arguments=dict(tool_call.arguments),
            )
            for tool_call in output.tool_calls
        ],
        provider=output.provider,
        model=output.model,
        usage=ModelUsage(
            input_tokens=output.usage.input_tokens,
            output_tokens=output.usage.output_tokens,
            cache_read_tokens=output.usage.cache_read_tokens,
            cache_write_tokens=output.usage.cache_write_tokens,
            reasoning_tokens=output.usage.reasoning_tokens,
            cost_usd=output.usage.cost_usd,
        ),
    )


def _recorded_exception(failure: ReplayModelFailure) -> Exception:
    error_class = type(failure.error_type, (RuntimeError,), {})
    error = error_class(failure.error_message)
    if failure.http_status is not None:
        error.status_code = failure.http_status
    return error


def _tool_result(step: ReplayToolStep) -> ToolResult:
    output = step.result
    return ToolResult(
        tool_call_id=output.tool_call_id,
        name=output.name,
        content=output.content,
        status=output.status,
        metadata=dict(output.metadata),
        structured_content=dict(output.structured_content),
    )
