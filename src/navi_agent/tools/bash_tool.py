from __future__ import annotations

import subprocess
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class BashTool(WorkspaceTool):
    def __init__(
        self,
        root=None,
        default_timeout_seconds: int = 20,
        max_timeout_seconds: int = 60,
        max_output_chars: int = 20_000,
    ) -> None:
        super().__init__(root=root)
        self._default_timeout_seconds = default_timeout_seconds
        self._max_timeout_seconds = max_timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a shell command inside the workspace."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "required": ["command"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        command = str(kwargs["command"])
        timeout_seconds = int(kwargs.get("timeout_seconds", self._default_timeout_seconds))
        timeout_seconds = max(1, min(timeout_seconds, self._max_timeout_seconds))
        try:
            cwd = self._resolve_path(kwargs.get("cwd"))
        except ValueError as exc:
            return ToolResult.error(
                name=self.name,
                content=str(exc),
                metadata={"cwd": kwargs.get("cwd")},
            )

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "").strip()
            stderr = (exc.stderr or "").strip()
            return ToolResult.error(
                name=self.name,
                content=f"Command timed out after {timeout_seconds} seconds",
                structured_content={
                    "exit_code": None,
                    "stdout": stdout,
                    "stderr": stderr,
                    "timed_out": True,
                },
                metadata={
                    "cwd": str(cwd),
                    "timeout_seconds": timeout_seconds,
                    "command": command,
                },
            )

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        truncated = False
        if len(stdout) > self._max_output_chars:
            stdout = stdout[: self._max_output_chars] + "\n...<truncated>"
            truncated = True
        if len(stderr) > self._max_output_chars:
            stderr = stderr[: self._max_output_chars] + "\n...<truncated>"
            truncated = True
        parts = [f"exit_code: {completed.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        result_cls = ToolResult.ok if completed.returncode == 0 else ToolResult.error
        return result_cls(
            name=self.name,
            content="\n".join(parts),
            structured_content={
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": truncated,
            },
            metadata={"cwd": str(cwd), "timeout_seconds": timeout_seconds, "command": command},
        )
