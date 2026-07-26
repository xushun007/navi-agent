from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState, solver

from evals.inspect.adapter import NaviInspectResult, navi_runtime_success
from navi_agent.app import AppRequest, ApplicationService
from navi_agent.config import ModelSettings, RuntimeSettings, load_config
from navi_agent.runtime import (
    AgentRuntime,
    InMemorySessionStore,
    RuntimeMode,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    build_transport,
)
from navi_agent.telemetry import InMemoryTraceStore


DATASET_PATH = Path(__file__).with_name("data") / "bfcl.jsonl"
BFCL_SYSTEM_PROMPT = (
    "Use a provided tool when and only when it is relevant to the request. "
    "Pass every value stated by the user as a tool argument. "
    "When several independent calls are requested, issue all required calls. "
    "If no provided tool is relevant, answer directly without calling a tool."
)


def load_bfcl_samples(path: Path = DATASET_PATH) -> list[Sample]:
    return [
        Sample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class BFCLInspectRunner:
    def __init__(
        self,
        *,
        transport,
        model: str,
        max_iterations: int = 30,
    ) -> None:
        self._transport = transport
        self._model = model
        self._max_iterations = max_iterations
        self._lock = Lock()

    def run(
        self,
        prompt: str,
        *,
        sample_id: str,
        functions: list[dict[str, Any]],
    ) -> NaviInspectResult:
        with self._lock:
            return self._run(prompt, sample_id=sample_id, functions=functions)

    def _run(
        self,
        prompt: str,
        *,
        sample_id: str,
        functions: list[dict[str, Any]],
    ) -> NaviInspectResult:
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=self._transport,
            tool_registry=_build_tool_registry(functions),
            session_store=InMemorySessionStore(),
            trace_store=trace_store,
            max_iterations=self._max_iterations,
            model=self._model,
        )
        app = ApplicationService(runtime)
        session_id = f"inspect:bfcl:{sample_id}:{uuid4().hex[:8]}"
        user_id = "inspect-bfcl"
        result = app.handle(
            AppRequest(
                session_id=session_id,
                user_id=user_id,
                message=prompt,
                system_prompt=BFCL_SYSTEM_PROMPT,
                source="inspect",
                mode=RuntimeMode.EVAL,
            )
        )
        trace = app.get_latest_trace(session_id=session_id, user_id=user_id)
        if trace is None:
            raise RuntimeError(f"Navi runtime did not record a trace for {sample_id}")
        return NaviInspectResult(
            session_id=session_id,
            run_id=result.run_id,
            trace_id=trace.trace_id,
            status=result.status,
            completion=result.final_response,
            iterations=trace.total_iterations,
            duration_ms=trace.duration_ms,
            input_tokens=sum(call.input_tokens for call in trace.model_calls),
            output_tokens=sum(call.output_tokens for call in trace.model_calls),
            cost_usd=sum(call.cost_usd or 0.0 for call in trace.model_calls),
            tool_calls=tuple(
                {
                    "name": execution.tool_name,
                    "arguments": execution.arguments,
                    "status": execution.status,
                }
                for execution in trace.tool_executions
            ),
        )


def build_bfcl_runner() -> BFCLInspectRunner:
    config = load_config()
    model_settings = ModelSettings.from_sources(config)
    runtime_settings = RuntimeSettings.from_sources(config)
    return BFCLInspectRunner(
        transport=build_transport(model_settings),
        model=model_settings.model,
        max_iterations=runtime_settings.max_iterations,
    )


@solver
def bfcl_solver(runner: BFCLInspectRunner):
    async def solve(state: TaskState, generate):
        result = await asyncio.to_thread(
            runner.run,
            state.user_prompt.text,
            sample_id=str(state.sample_id),
            functions=list(state.metadata["functions"]),
        )
        state.messages.append(ChatMessageAssistant(content=result.completion))
        state.output.completion = result.completion
        state.metadata["navi"] = result.metadata()
        return state

    return solve


@scorer(metrics=[accuracy()])
def bfcl_tool_call_correctness():
    async def score(state: TaskState, target: Target):
        actual_calls = list((state.metadata.get("navi") or {}).get("tool_calls") or [])
        expected_calls = list(state.metadata.get("expected_calls") or [])
        passed, explanation = match_tool_calls(actual_calls, expected_calls)
        return Score(value="C" if passed else "I", explanation=explanation)

    return score


@task
def navi_bfcl(runner: BFCLInspectRunner | None = None) -> Task:
    return Task(
        dataset=load_bfcl_samples(),
        solver=bfcl_solver(runner or build_bfcl_runner()),
        scorer=[
            bfcl_tool_call_correctness(),
            navi_runtime_success(),
        ],
        metadata={
            "agent": "navi-agent",
            "dataset": "BFCL v4 curated",
            "sample_count": 10,
        },
    )


def match_tool_calls(
    actual_calls: list[dict[str, Any]],
    expected_calls: list[dict[str, Any]],
) -> tuple[bool, str]:
    failed_calls = [
        call for call in actual_calls if call.get("status") != "success"
    ]
    if failed_calls:
        return False, f"tool execution failed: {_render_calls(failed_calls)}"
    if len(actual_calls) != len(expected_calls):
        return (
            False,
            f"expected {len(expected_calls)} successful calls, "
            f"observed {len(actual_calls)}: {_render_calls(actual_calls)}",
        )

    unmatched = list(expected_calls)
    for actual in actual_calls:
        match_index = next(
            (
                index
                for index, expected in enumerate(unmatched)
                if _call_matches(actual, expected)
            ),
            None,
        )
        if match_index is None:
            return False, f"unexpected call: {_render_calls([actual])}"
        unmatched.pop(match_index)

    if unmatched:
        return False, f"missing calls: {_render_calls(unmatched)}"
    return True, f"matched {len(expected_calls)} expected tool call(s)"


def _build_tool_registry(functions: list[dict[str, Any]]) -> ToolRegistry:
    return ToolRegistry(
        definitions=[
            ToolDefinition(
                name=str(function["name"]),
                description=str(function.get("description") or ""),
                parameters=_normalize_schema(dict(function["parameters"])),
                handler=_recording_handler(str(function["name"])),
                toolset="bfcl",
            )
            for function in functions
        ]
    )


def _recording_handler(name: str):
    def handler(**arguments: Any) -> ToolResult:
        return ToolResult.ok(
            name,
            json.dumps(
                {"tool": name, "arguments": arguments},
                ensure_ascii=False,
                sort_keys=True,
            ),
            structured_content={"arguments": arguments},
        )

    return handler


def _normalize_schema(value: Any) -> Any:
    if isinstance(value, dict):
        normalized = {
            key: _normalize_schema(item)
            for key, item in value.items()
        }
        if normalized.get("type") == "dict":
            normalized["type"] = "object"
        elif normalized.get("type") == "float":
            normalized["type"] = "number"
        return normalized
    if isinstance(value, list):
        return [_normalize_schema(item) for item in value]
    return value


def _call_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    if len(expected) != 1:
        return False
    expected_name, expected_arguments = next(iter(expected.items()))
    if actual.get("name") != expected_name:
        return False
    actual_arguments = actual.get("arguments")
    if not isinstance(actual_arguments, dict):
        return False
    if not set(actual_arguments).issubset(expected_arguments):
        return False
    return all(
        (
            key in actual_arguments
            and _matches_any(actual_arguments[key], allowed_values)
        )
        or (key not in actual_arguments and "" in allowed_values)
        for key, allowed_values in expected_arguments.items()
    )


def _matches_any(actual: Any, allowed_values: list[Any]) -> bool:
    return any(_value_matches(actual, allowed) for allowed in allowed_values)


def _value_matches(actual: Any, allowed: Any) -> bool:
    if isinstance(allowed, dict):
        return (
            isinstance(actual, dict)
            and set(actual) == set(allowed)
            and all(_matches_any(actual[key], options) for key, options in allowed.items())
        )
    return actual == allowed


def _render_calls(calls: list[dict[str, Any]]) -> str:
    return json.dumps(calls, ensure_ascii=False, sort_keys=True)
