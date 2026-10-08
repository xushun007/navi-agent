from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, TypeVar

from evals.inspect.swe_bench import InspectRuntimeRunner, build_inspect_runtime_runner
from navi_agent.runtime import ToolDefinition, ToolRegistry, ToolResult

if TYPE_CHECKING:
    from pier.environments.base import BaseEnvironment


_T = TypeVar("_T")

DEEP_SWE_SYSTEM_PROMPT = """Work directly in the provided repository to complete the task.
Inspect the code and tests, make the smallest correct implementation, and run focused
verification. Do not merely describe a solution: make the changes in the environment.
Before you finish, inspect the diff and commit the intended changes with git. DeepSWE
grades the committed patch in a separate clean verifier environment. Finish with a
concise summary of the implementation and verification performed."""


class PierSandboxBridge:
    """Expose a Pier task environment through Navi's small evaluation toolset."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        environment: BaseEnvironment,
        tool_timeout_seconds: int = 300,
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
                    description="Execute a shell command in the DeepSWE task repository.",
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
                    toolset="deep-swe",
                )
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
                    command,
                    cwd=cwd,
                    timeout_sec=timeout,
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
        content = [f"exit_code: {result.return_code}"]
        if stdout:
            content.append(f"stdout:\n{stdout}")
        if stderr:
            content.append(f"stderr:\n{stderr}")
        result_factory = ToolResult.ok if result.return_code == 0 else ToolResult.error
        return result_factory(
            "bash",
            "\n".join(content),
            structured_content={
                "exit_code": result.return_code,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
            },
        )

    def _wait(self, awaitable: Awaitable[_T]) -> _T:
        return asyncio.run_coroutine_threadsafe(awaitable, self._loop).result()

    def _truncate(self, value: str) -> str:
        if len(value) <= self._max_output_chars:
            return value.strip()
        return f"{value[: self._max_output_chars].strip()}\n...<truncated>"


def _load_base_agent():
    try:
        from pier.agents.base import BaseAgent
    except ImportError as exc:
        raise RuntimeError(
            "DeepSWE evaluation requires: uv sync --extra deep-swe"
        ) from exc
    return BaseAgent


class NaviDeepSweAgent(_load_base_agent()):
    """Run Navi inside a Pier task environment without changing Navi core."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._runner = build_inspect_runtime_runner()

    @staticmethod
    def name() -> str:
        return "navi-agent"

    def version(self) -> str:
        return "0.3.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    async def run(self, instruction: str, environment: BaseEnvironment, context) -> None:
        loop = asyncio.get_running_loop()
        result = await asyncio.to_thread(
            self._runner.run,
            instruction,
            sample_id=environment.session_id,
            sandbox_bridge=PierSandboxBridge(loop=loop, environment=environment),
            suite="deep-swe-1-1",
            system_prompt=DEEP_SWE_SYSTEM_PROMPT,
        )
        context.n_input_tokens = result.input_tokens
        context.n_output_tokens = result.output_tokens
        context.cost_usd = result.cost_usd
        context.n_agent_steps = result.iterations
        context.metadata = {
            "navi_run_id": result.run_id,
            "navi_trace_id": result.trace_id,
            "navi_status": result.status,
            "completion_verified": result.completion_verified,
            "completion_reason": result.completion_reason,
        }
