from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from dataclasses import dataclass
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
    AutoApproveApprovalProvider,
    InMemorySessionStore,
    PromptBuilder,
    RuntimeMode,
    build_transport,
)
from navi_agent.telemetry import InMemoryTraceStore
from navi_agent.tools.defaults import build_default_tool_registry


DATASET_PATH = Path(__file__).with_name("data") / "agent_bench_os.jsonl"
AGENT_BENCH_SYSTEM_PROMPT = (
    "Complete the operating-system task using only the provided tools and the "
    "current isolated workspace. Never access paths outside the workspace. "
    "Inspect the environment instead of guessing. When the task asks for an "
    "answer, return only that answer without explanation."
)


def load_agent_bench_os_samples(path: Path = DATASET_PATH) -> list[Sample]:
    return [
        Sample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@dataclass(frozen=True, slots=True)
class AgentBenchOSResult:
    navi: NaviInspectResult
    environment_passed: bool
    environment_explanation: str

    def metadata(self) -> dict[str, object]:
        metadata = self.navi.metadata()
        metadata["environment_passed"] = self.environment_passed
        metadata["environment_explanation"] = self.environment_explanation
        return metadata


class AgentBenchOSRunner:
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
        setup: dict[str, Any],
        checks: list[dict[str, Any]],
    ) -> AgentBenchOSResult:
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="navi-agentbench-os-") as raw_path:
                workspace = Path(raw_path)
                prepare_workspace(workspace, setup)
                navi_result = self._run_navi(
                    prompt,
                    sample_id=sample_id,
                    workspace=workspace,
                )
                environment_passed, explanation = evaluate_workspace(
                    workspace,
                    checks,
                )
                return AgentBenchOSResult(
                    navi=navi_result,
                    environment_passed=environment_passed,
                    environment_explanation=explanation,
                )

    def _run_navi(
        self,
        prompt: str,
        *,
        sample_id: str,
        workspace: Path,
    ) -> NaviInspectResult:
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=self._transport,
            tool_registry=build_default_tool_registry(
                root=workspace,
                approval_provider=AutoApproveApprovalProvider(),
            ),
            session_store=InMemorySessionStore(),
            prompt_builder=PromptBuilder(project_context_root=workspace),
            trace_store=trace_store,
            enabled_toolsets=["terminal", "file"],
            max_iterations=self._max_iterations,
            model=self._model,
            cwd=str(workspace),
        )
        app = ApplicationService(runtime)
        session_id = f"inspect:agentbench-os:{sample_id}:{uuid4().hex[:8]}"
        user_id = "inspect-agentbench-os"
        result = app.handle(
            AppRequest(
                session_id=session_id,
                user_id=user_id,
                message=prompt,
                system_prompt=AGENT_BENCH_SYSTEM_PROMPT,
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


def build_agent_bench_os_runner() -> AgentBenchOSRunner:
    config = load_config()
    model_settings = ModelSettings.from_sources(config)
    runtime_settings = RuntimeSettings.from_sources(config)
    return AgentBenchOSRunner(
        transport=build_transport(model_settings),
        model=model_settings.model,
        max_iterations=runtime_settings.max_iterations,
    )


@solver
def agent_bench_os_solver(runner: AgentBenchOSRunner):
    async def solve(state: TaskState, generate):
        result = await asyncio.to_thread(
            runner.run,
            state.user_prompt.text,
            sample_id=str(state.sample_id),
            setup=dict(state.metadata["setup"]),
            checks=list(state.metadata["checks"]),
        )
        state.messages.append(ChatMessageAssistant(content=result.navi.completion))
        state.output.completion = result.navi.completion
        state.metadata["navi"] = result.metadata()
        return state

    return solve


@scorer(metrics=[accuracy()])
def agent_bench_os_task_success():
    async def score(state: TaskState, target: Target):
        metadata = state.metadata.get("navi") or {}
        answer = state.output.completion.strip()
        expected = target.text.strip()
        answer_passed = not expected or answer == expected
        environment_passed = bool(metadata.get("environment_passed"))
        passed = answer_passed and environment_passed
        return Score(
            value="C" if passed else "I",
            answer=answer,
            explanation=(
                f"answer_passed={answer_passed} "
                f"environment_passed={environment_passed} "
                f"environment={metadata.get('environment_explanation')}"
            ),
        )

    return score


@task
def navi_agent_bench_os(runner: AgentBenchOSRunner | None = None) -> Task:
    return Task(
        dataset=load_agent_bench_os_samples(),
        solver=agent_bench_os_solver(runner or build_agent_bench_os_runner()),
        scorer=[
            agent_bench_os_task_success(),
            navi_runtime_success(),
        ],
        metadata={
            "agent": "navi-agent",
            "dataset": "AgentBench OS dev curated",
            "sample_count": 10,
        },
    )


def prepare_workspace(workspace: Path, setup: dict[str, Any]) -> None:
    for directory in setup.get("directories", []):
        (workspace / str(directory)).mkdir(parents=True, exist_ok=True)

    for relative_path, content in setup.get("files", {}).items():
        path = workspace / str(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")

    for relative_path, raw_mode in setup.get("modes", {}).items():
        os.chmod(workspace / str(relative_path), int(str(raw_mode), 8))

    old_timestamp = time.time() - (48 * 60 * 60)
    for relative_path in setup.get("old_files", []):
        os.utime(workspace / str(relative_path), (old_timestamp, old_timestamp))


def evaluate_workspace(
    workspace: Path,
    checks: list[dict[str, Any]],
) -> tuple[bool, str]:
    if not checks:
        return True, "no state mutation required"

    for check in checks:
        result = subprocess.run(
            ["/bin/sh", "-c", check["command"]],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return (
                False,
                f"check failed: {check['command']} stderr={result.stderr.strip()}",
            )
        expected_stdout = check.get("stdout")
        if expected_stdout is not None and result.stdout.strip() != expected_stdout:
            return (
                False,
                f"check output mismatch: {check['command']} "
                f"expected={expected_stdout!r} actual={result.stdout.strip()!r}",
            )
        expected_numeric = check.get("numeric_stdout")
        if expected_numeric is not None:
            try:
                actual_numeric = float(result.stdout.strip())
            except ValueError:
                return (
                    False,
                    f"check output is not numeric: {check['command']} "
                    f"actual={result.stdout.strip()!r}",
                )
            tolerance = float(check.get("tolerance", 1e-5))
            if abs(actual_numeric - float(expected_numeric)) >= tolerance:
                return (
                    False,
                    f"check numeric mismatch: {check['command']} "
                    f"expected={expected_numeric!r} actual={actual_numeric!r}",
                )
    return True, f"passed {len(checks)} workspace check(s)"
