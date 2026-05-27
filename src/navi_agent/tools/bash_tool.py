from __future__ import annotations

import re
import shlex
import subprocess
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class BashTool(WorkspaceTool):
    _DANGEROUS_COMMAND_REASONS = {
        "sudo": "sudo commands require approval",
        "shutdown": "shutdown commands are not allowed",
        "reboot": "reboot commands are not allowed",
        "halt": "halt commands are not allowed",
        "poweroff": "poweroff commands are not allowed",
        "mkfs": "filesystem formatting commands are not allowed",
        "dd": "raw device write commands are not allowed",
    }
    _WORKSPACE_PATH_COMMANDS = {"cd", "ls", "cat", "touch", "mkdir", "rm", "mv", "cp"}

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
        command = str(kwargs["command"]).strip()
        if not command:
            return ToolResult.error(name=self.name, content="Command must not be empty")
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

        inspection_error = self._inspect_command(command, cwd)
        if inspection_error is not None:
            return inspection_error

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
                    "command": command,
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
                "command": command,
                "command_name": self._command_name(command),
                "timed_out": False,
            },
            metadata={"cwd": str(cwd), "timeout_seconds": timeout_seconds, "command": command},
        )

    def _inspect_command(self, command: str, cwd) -> ToolResult | None:
        if re.search(r"(^|[;&|])\s*[^&]*&\s*$", command):
            return ToolResult.error(
                name=self.name,
                content="Background commands are not supported",
                structured_content={"command": command, "background_requested": True},
            )

        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            return ToolResult.error(
                name=self.name,
                content=f"Invalid shell command: {exc}",
                structured_content={"command": command},
            )

        if not tokens:
            return ToolResult.error(name=self.name, content="Command must not be empty")

        command_name = tokens[0]
        dangerous_reason = self._DANGEROUS_COMMAND_REASONS.get(command_name)
        if dangerous_reason is not None:
            return ToolResult.error(
                name=self.name,
                content=dangerous_reason,
                structured_content={"command": command, "command_name": command_name},
            )

        if re.search(r"\brm\s+-[^\n]*r[^\n]*f[^\n]*\s+(/|~)\b", command):
            return ToolResult.error(
                name=self.name,
                content="Destructive root-level delete commands are not allowed",
                structured_content={"command": command, "command_name": command_name},
            )

        if command_name in self._WORKSPACE_PATH_COMMANDS:
            for token in tokens[1:]:
                if token.startswith("-"):
                    continue
                try:
                    self._resolve_command_path(token, cwd)
                except ValueError as exc:
                    return ToolResult.error(
                        name=self.name,
                        content=str(exc),
                        structured_content={
                            "command": command,
                            "command_name": command_name,
                            "path": token,
                        },
                    )

        return None

    def _resolve_command_path(self, token: str, cwd) -> None:
        if token in {".", ".."}:
            target = cwd / token
        elif token.startswith("/"):
            target = token
        elif token.startswith("~") or "/" in token or token.startswith("."):
            target = str(cwd / token)
        else:
            return
        self._resolve_path(target)

    def _command_name(self, command: str) -> str | None:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return None
        return tokens[0] if tokens else None
