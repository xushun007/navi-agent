from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from threading import Lock
from typing import Any, TypeVar
from uuid import uuid4

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageAssistant
from inspect_ai.solver import TaskState, solver
from inspect_ai.util import SandboxEnvironment, sandbox

from evals.inspect.adapter import NaviInspectResult
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


SWE_BENCH_DATASET = "princeton-nlp/SWE-bench_Verified"
SWE_BENCH_REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
SWE_BENCH_SAMPLE_IDS = (
    "astropy__astropy-12907",
    "django__django-11790",
    "django__django-11815",
    "matplotlib__matplotlib-13989",
    "mwaskom__seaborn-3069",
    "pallets__flask-5014",
    "psf__requests-1142",
    "pydata__xarray-2905",
    "pylint-dev__pylint-4551",
    "pytest-dev__pytest-10051",
    "scikit-learn__scikit-learn-10297",
    "sphinx-doc__sphinx-10323",
    "sphinx-doc__sphinx-10435",
    "sympy__sympy-11618",
    "sympy__sympy-12096",
)
SWE_BENCH_SYSTEM_PROMPT = (
    "Work directly in the current repository to solve the reported issue. "
    "Inspect the relevant code, make the smallest correct change, and run focused tests. "
    "Do not only describe a solution: edit the repository. "
    "Finish with a concise summary of the change and tests run."
)
_T = TypeVar("_T")


class InspectSandboxBridge:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        environment: SandboxEnvironment,
        tool_timeout_seconds: int = 210,
        max_output_chars: int = 20_000,
    ) -> None:
        self._loop = loop
        self._environment = environment
        self._tool_timeout_seconds = tool_timeout_seconds
        self._max_output_chars = max_output_chars

    def tool_registry(self) -> ToolRegistry:
        return ToolRegistry(
            definitions=[
                ToolDefinition(
                    name="bash",
                    description="Execute a shell command in the evaluation repository.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "cwd": {"type": "string"},
                            "timeout_seconds": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": self._tool_timeout_seconds,
                            },
                        },
                        "required": ["command"],
                    },
                    handler=self._bash,
                    toolset="swe-bench",
                ),
                ToolDefinition(
                    name="read_file",
                    description="Read a text file from the evaluation repository.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "start_line": {"type": "integer", "minimum": 1},
                            "line_count": {"type": "integer", "minimum": 1},
                        },
                        "required": ["path"],
                    },
                    handler=self._read_file,
                    toolset="swe-bench",
                ),
                ToolDefinition(
                    name="write_file",
                    description="Write a text file in the evaluation repository.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                    handler=self._write_file,
                    toolset="swe-bench",
                ),
                ToolDefinition(
                    name="patch",
                    description="Replace exact text in a file in the evaluation repository.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "old": {"type": "string"},
                            "new": {"type": "string"},
                            "replace_all": {"type": "boolean"},
                        },
                        "required": ["path", "old", "new"],
                    },
                    handler=self._patch,
                    toolset="swe-bench",
                ),
            ]
        )

    def _bash(
        self,
        *,
        command: str,
        cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ToolResult:
        timeout = min(
            int(timeout_seconds or self._tool_timeout_seconds),
            self._tool_timeout_seconds,
        )
        try:
            result = self._wait(
                self._environment.exec(
                    ["bash", "--login", "-c", command],
                    cwd=cwd,
                    timeout=timeout,
                    timeout_retry=False,
                )
            )
        except TimeoutError:
            return ToolResult.error(
                "bash",
                f"Command timed out after {timeout} seconds",
                structured_content={"timed_out": True, "command": command},
            )

        stdout = self._truncate(result.stdout or "")
        stderr = self._truncate(result.stderr or "")
        content = [f"exit_code: {result.returncode}"]
        if stdout:
            content.append(f"stdout:\n{stdout}")
        if stderr:
            content.append(f"stderr:\n{stderr}")
        result_factory = ToolResult.ok if result.returncode == 0 else ToolResult.error
        return result_factory(
            "bash",
            "\n".join(content),
            structured_content={
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
            },
        )

    def _read_file(
        self,
        *,
        path: str,
        start_line: int = 1,
        line_count: int = 200,
    ) -> ToolResult:
        try:
            content = self._wait(self._environment.read_file(path))
        except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
            return ToolResult.error("read_file", str(exc), metadata={"path": path})

        lines = str(content).splitlines()
        start = max(1, int(start_line))
        count = max(1, min(int(line_count), 500))
        selected = lines[start - 1 : start - 1 + count]
        rendered = "\n".join(
            f"{number}: {line}" for number, line in enumerate(selected, start=start)
        )
        truncated = start - 1 + count < len(lines)
        if truncated:
            rendered += f"\n\nFile has more lines. Continue with start_line={start + len(selected)}."
        return ToolResult.ok(
            "read_file",
            rendered,
            structured_content={
                "path": path,
                "start_line": start,
                "line_count": len(selected),
                "total_lines": len(lines),
                "truncated": truncated,
            },
        )

    def _write_file(self, *, path: str, content: str) -> ToolResult:
        try:
            self._wait(self._environment.write_file(path, content))
        except (IsADirectoryError, PermissionError) as exc:
            return ToolResult.error("write_file", str(exc), metadata={"path": path})
        return ToolResult.ok(
            "write_file",
            f"bytes_written: {len(content.encode('utf-8'))}",
            structured_content={"path": path, "bytes_written": len(content.encode("utf-8"))},
        )

    def _patch(
        self,
        *,
        path: str,
        old: str,
        new: str,
        replace_all: bool = False,
    ) -> ToolResult:
        if not old:
            return ToolResult.error("patch", "Patch 'old' text must not be empty")
        try:
            current = str(self._wait(self._environment.read_file(path)))
        except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
            return ToolResult.error("patch", str(exc), metadata={"path": path})
        if old not in current:
            return ToolResult.error(
                "patch",
                "patch_failed: target text not found",
                structured_content={"path": path, "applied": False},
            )
        replacements = current.count(old) if replace_all else 1
        updated = current.replace(old, new, replacements)
        self._wait(self._environment.write_file(path, updated))
        return ToolResult.ok(
            "patch",
            f"patched: {replacements} replacement{'s' if replacements != 1 else ''}",
            structured_content={
                "path": path,
                "applied": True,
                "replacements": replacements,
                "replace_all": replace_all,
            },
        )

    def _wait(self, awaitable: Awaitable[_T]) -> _T:
        return asyncio.run_coroutine_threadsafe(awaitable, self._loop).result()

    def _truncate(self, value: str) -> str:
        if len(value) <= self._max_output_chars:
            return value.strip()
        return f"{value[: self._max_output_chars].strip()}\n...<truncated>"


class SWEBenchInspectRunner:
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
        sandbox_bridge: InspectSandboxBridge,
    ) -> NaviInspectResult:
        with self._lock:
            trace_store = InMemoryTraceStore()
            runtime = AgentRuntime(
                transport=self._transport,
                tool_registry=sandbox_bridge.tool_registry(),
                session_store=InMemorySessionStore(),
                trace_store=trace_store,
                max_iterations=self._max_iterations,
                model=self._model,
            )
            app = ApplicationService(runtime)
            session_id = f"inspect:swe-bench-verified:{sample_id}:{uuid4().hex[:8]}"
            user_id = "inspect-swe-bench-verified"
            result = app.handle(
                AppRequest(
                    session_id=session_id,
                    user_id=user_id,
                    message=prompt,
                    system_prompt=SWE_BENCH_SYSTEM_PROMPT,
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


def build_swe_bench_runner() -> SWEBenchInspectRunner:
    config = load_config()
    model_settings = ModelSettings.from_sources(config)
    runtime_settings = RuntimeSettings.from_sources(config)
    return SWEBenchInspectRunner(
        transport=build_transport(model_settings),
        model=model_settings.model,
        max_iterations=runtime_settings.max_iterations,
    )


@solver
def swe_bench_solver(runner: SWEBenchInspectRunner):
    async def solve(state: TaskState, generate):
        loop = asyncio.get_running_loop()
        result = await asyncio.to_thread(
            runner.run,
            state.user_prompt.text,
            sample_id=str(state.sample_id),
            sandbox_bridge=InspectSandboxBridge(
                loop=loop,
                environment=sandbox(),
            ),
        )
        state.messages.append(ChatMessageAssistant(content=result.completion))
        state.output.completion = result.completion
        state.metadata["navi"] = result.metadata()
        return state

    return solve


def select_swe_bench_samples(
    samples: list[Sample],
    sample_ids: tuple[str, ...] = SWE_BENCH_SAMPLE_IDS,
) -> list[Sample]:
    by_id = {str(sample.id): sample for sample in samples}
    missing = [sample_id for sample_id in sample_ids if sample_id not in by_id]
    if missing:
        raise ValueError(f"SWE-bench samples missing from pinned dataset: {', '.join(missing)}")
    return [by_id[sample_id] for sample_id in sample_ids]


def _official_swe_bench_task() -> Task:
    try:
        from inspect_evals.swe_bench import swe_bench
    except ImportError as exc:
        raise RuntimeError(
            "SWE-bench evaluation requires: uv sync --extra swe-bench"
        ) from exc
    return swe_bench(
        dataset=SWE_BENCH_DATASET,
        revision=SWE_BENCH_REVISION,
        tool_timeout=210,
    )


@task
def navi_swe_bench_verified(
    runner: SWEBenchInspectRunner | None = None,
    *,
    official_task_factory: Callable[[], Task] = _official_swe_bench_task,
) -> Task:
    benchmark = official_task_factory()
    benchmark.dataset = MemoryDataset(
        select_swe_bench_samples(list(benchmark.dataset)),
        name="navi-swe-bench-verified",
        location=SWE_BENCH_DATASET,
    )
    benchmark.solver = swe_bench_solver(runner or build_swe_bench_runner())
    benchmark.metadata = {
        **(benchmark.metadata or {}),
        "agent": "navi-agent",
        "dataset": SWE_BENCH_DATASET,
        "dataset_revision": SWE_BENCH_REVISION,
        "sample_count": len(SWE_BENCH_SAMPLE_IDS),
    }
    return benchmark
