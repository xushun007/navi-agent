from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from navi_agent.tooling import ToolContext, ToolResult
from navi_agent.bash_command import assess_bash_command
from navi_agent.safety import sanitized_subprocess_env

from .workspace_tool import WorkspaceTool

if TYPE_CHECKING:
    from navi_agent.runtime.tasks.background import BackgroundTaskManager


class _BoundedTextBuffer:
    def __init__(self, max_chars: int) -> None:
        self._max_chars = max(1, max_chars)
        self._chunks: deque[str] = deque()
        self._char_count = 0
        self._truncated = False
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        with self._lock:
            self._chunks.append(text)
            self._char_count += len(text)
            while self._char_count > self._max_chars:
                overflow = self._char_count - self._max_chars
                first = self._chunks.popleft()
                if len(first) > overflow:
                    self._chunks.appendleft(first[overflow:])
                    self._char_count -= overflow
                else:
                    self._char_count -= len(first)
                self._truncated = True

    def render(self) -> tuple[str, bool]:
        with self._lock:
            text = "".join(self._chunks).strip()
            truncated = self._truncated
        if truncated:
            text = f"...<truncated>\n{text}"
        return text, truncated


@dataclass(slots=True)
class _RunningCommand:
    process: subprocess.Popen
    stdout_buffer: _BoundedTextBuffer
    stderr_buffer: _BoundedTextBuffer
    stdout_thread: threading.Thread
    stderr_thread: threading.Thread
    emit_output: list[Any]
    started_at: float


class BashTool(WorkspaceTool):
    _WORKSPACE_PATH_COMMANDS = {
        "cat",
        "cd",
        "cp",
        "find",
        "git",
        "grep",
        "head",
        "ls",
        "mkdir",
        "mv",
        "rg",
        "rm",
        "sort",
        "stat",
        "tail",
        "touch",
        "wc",
    }

    def __init__(
        self,
        root=None,
        default_timeout_seconds: int | None = 60,
        max_timeout_seconds: int = 60,
        default_yield_time_ms: int = 10_000,
        max_yield_time_ms: int = 30_000,
        max_output_chars: int = 20_000,
        background_task_manager: BackgroundTaskManager | None = None,
        additional_roots: Iterable[Path] | None = None,
    ) -> None:
        super().__init__(root=root, additional_roots=additional_roots)
        self._default_timeout_seconds = default_timeout_seconds
        self._max_timeout_seconds = max_timeout_seconds
        self._default_yield_time_ms = default_yield_time_ms
        self._max_yield_time_ms = max_yield_time_ms
        self._max_output_chars = max_output_chars
        self._background_task_manager = background_task_manager

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a shell command from the workspace or an explicitly added directory."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": self._max_timeout_seconds,
                    "description": "Optional maximum command runtime.",
                },
                "yield_time_ms": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": self._max_yield_time_ms,
                    "description": (
                        "Wait before returning a background task for a still-running command."
                    ),
                },
                "background": {"type": "boolean"},
            },
            "required": ["command"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        command = str(kwargs["command"]).strip()
        if not command:
            return ToolResult.error(name=self.name, content="Command must not be empty")
        timeout_value = kwargs.get("timeout_seconds", self._default_timeout_seconds)
        timeout_seconds = (
            max(1, min(int(timeout_value), self._max_timeout_seconds))
            if timeout_value is not None
            else None
        )
        yield_time_ms = max(
            1,
            min(
                int(kwargs.get("yield_time_ms", self._default_yield_time_ms)),
                self._max_yield_time_ms,
            ),
        )
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

        if kwargs.get("background") is True:
            if context is None or self._background_task_manager is None:
                return ToolResult.error(
                    name=self.name,
                    content="Background execution is not available",
                    structured_content={"command": command, "background": True},
                )
            cancel_event = threading.Event()
            cancellation_requested = self._combine_cancellation(
                context.cancellation_requested,
                cancel_event.is_set,
            )
            try:
                task = self._background_task_manager.submit(
                    session_id=context.session_id,
                    user_id=context.user_id,
                    description=command,
                    cancel_callback=cancel_event.set,
                    runner=lambda: self._execute(
                        command=command,
                        cwd=cwd,
                        timeout_seconds=timeout_seconds,
                        emit_output=None,
                        cancellation_requested=cancellation_requested,
                    ),
                )
            except RuntimeError as exc:
                return ToolResult.error(name=self.name, content=str(exc))
            return ToolResult.ok(
                name=self.name,
                content=(
                    f"Background task started\n"
                    f"task_id: {task.task_id}\n"
                    f"command: {command}"
                ),
                structured_content={
                    "task_id": task.task_id,
                    "status": task.status,
                    "command": command,
                    "background": True,
                },
                metadata={"cwd": str(cwd), "timeout_seconds": timeout_seconds, "command": command},
            )

        if context is not None and self._background_task_manager is not None:
            return self._execute_with_yield(
                context=context,
                command=command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                yield_time_ms=yield_time_ms,
            )

        return self._execute(
            command=command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            emit_output=context.emit_output if context is not None else None,
            cancellation_requested=(
                context.cancellation_requested if context is not None else None
            ),
        )

    def preflight(
        self,
        context: ToolContext | None = None,
        **kwargs: Any,
    ) -> ToolResult | None:
        command = str(kwargs.get("command") or "").strip()
        if not command:
            return ToolResult.error(name=self.name, content="Command must not be empty")
        try:
            cwd = self._resolve_path(kwargs.get("cwd"))
        except ValueError as exc:
            return ToolResult.error(
                name=self.name,
                content=str(exc),
                metadata={"cwd": kwargs.get("cwd")},
            )
        return self._inspect_command(command, cwd)

    def _execute(
        self,
        *,
        command: str,
        cwd,
        timeout_seconds: int | None,
        emit_output,
        cancellation_requested,
    ) -> ToolResult:
        if cancellation_requested is not None and cancellation_requested():
            return self._cancelled_result(command, cwd, timeout_seconds, "", "", emit_output)
        running = self._start_process(command, cwd, emit_output)
        outcome = self._wait_for_process(
            running,
            timeout_seconds=timeout_seconds,
            cancellation_requested=cancellation_requested,
        )
        return self._finish_process(
            running,
            outcome=outcome,
            command=command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )

    def _execute_with_yield(
        self,
        *,
        context: ToolContext,
        command: str,
        cwd,
        timeout_seconds: int | None,
        yield_time_ms: int,
    ) -> ToolResult:
        cancel_event = threading.Event()
        cancellation_requested = self._combine_cancellation(
            context.cancellation_requested,
            cancel_event.is_set,
        )
        if cancellation_requested():
            return self._cancelled_result(
                command,
                cwd,
                timeout_seconds,
                "",
                "",
                context.emit_output,
            )
        running = self._start_process(command, cwd, context.emit_output)
        outcome = self._wait_for_process(
            running,
            timeout_seconds=timeout_seconds,
            cancellation_requested=cancellation_requested,
            yield_time_ms=yield_time_ms,
        )
        if outcome != "yielded":
            return self._finish_process(
                running,
                outcome=outcome,
                command=command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
            )

        running.emit_output[0] = None
        try:
            task = self._background_task_manager.submit(
                session_id=context.session_id,
                user_id=context.user_id,
                description=command,
                cancel_callback=cancel_event.set,
                runner=lambda: self._resume_process(
                    running,
                    command=command,
                    cwd=cwd,
                    timeout_seconds=timeout_seconds,
                    cancellation_requested=cancellation_requested,
                ),
            )
        except RuntimeError:
            outcome = self._wait_for_process(
                running,
                timeout_seconds=timeout_seconds,
                cancellation_requested=cancellation_requested,
            )
            return self._finish_process(
                running,
                outcome=outcome,
                command=command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
            )

        return ToolResult.ok(
            name=self.name,
            content=(
                f"Command still running\n"
                f"task_id: {task.task_id}\n"
                f"command: {command}"
            ),
            structured_content={
                "task_id": task.task_id,
                "status": task.status,
                "command": command,
                "background": True,
                "yielded": True,
                "timed_out": False,
                "exit_code": None,
            },
            metadata={
                "cwd": str(cwd),
                "timeout_seconds": timeout_seconds,
                "yield_time_ms": yield_time_ms,
                "command": command,
            },
        )

    def _resume_process(
        self,
        running: _RunningCommand,
        *,
        command: str,
        cwd,
        timeout_seconds: int | None,
        cancellation_requested,
    ) -> ToolResult:
        outcome = self._wait_for_process(
            running,
            timeout_seconds=timeout_seconds,
            cancellation_requested=cancellation_requested,
        )
        return self._finish_process(
            running,
            outcome=outcome,
            command=command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )

    def _start_process(self, command: str, cwd, emit_output) -> _RunningCommand:
        stdout_buffer = _BoundedTextBuffer(self._max_output_chars)
        stderr_buffer = _BoundedTextBuffer(self._max_output_chars)
        emit_output_holder = [emit_output]
        env = sanitized_subprocess_env(os.environ)
        env.pop("CDPATH", None)
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        stdout_thread = threading.Thread(
            target=self._consume_stream,
            args=(process.stdout, "stdout", stdout_buffer, emit_output_holder),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._consume_stream,
            args=(process.stderr, "stderr", stderr_buffer, emit_output_holder),
            daemon=True,
        )
        running = _RunningCommand(
            process=process,
            stdout_buffer=stdout_buffer,
            stderr_buffer=stderr_buffer,
            stdout_thread=stdout_thread,
            stderr_thread=stderr_thread,
            emit_output=emit_output_holder,
            started_at=time.monotonic(),
        )
        stdout_thread.start()
        stderr_thread.start()
        return running

    @staticmethod
    def _wait_for_process(
        running: _RunningCommand,
        *,
        timeout_seconds: int | None,
        cancellation_requested,
        yield_time_ms: int | None = None,
    ) -> str:
        timeout_deadline = (
            running.started_at + timeout_seconds if timeout_seconds is not None else None
        )
        yield_deadline = (
            time.monotonic() + (yield_time_ms / 1000) if yield_time_ms is not None else None
        )
        while running.process.poll() is None:
            if cancellation_requested is not None and cancellation_requested():
                return "cancelled"
            now = time.monotonic()
            if timeout_deadline is not None and now >= timeout_deadline:
                return "timed_out"
            if yield_deadline is not None and now >= yield_deadline:
                return "yielded"
            time.sleep(0.05)
        return "completed"

    def _finish_process(
        self,
        running: _RunningCommand,
        *,
        outcome: str,
        command: str,
        cwd,
        timeout_seconds: int | None,
    ) -> ToolResult:
        if outcome in {"timed_out", "cancelled"}:
            self._terminate_process(running.process)
        self._join_streams(running)
        stdout, stdout_truncated = running.stdout_buffer.render()
        stderr, stderr_truncated = running.stderr_buffer.render()
        truncated = stdout_truncated or stderr_truncated
        emit_output = running.emit_output[0]

        if outcome == "timed_out":
            return ToolResult.error(
                name=self.name,
                content=f"Command timed out after {timeout_seconds} seconds",
                structured_content={
                    "exit_code": None,
                    "stdout": stdout,
                    "stderr": stderr,
                    "truncated": truncated,
                    "timed_out": True,
                    "command": command,
                    "streaming": emit_output is not None,
                },
                metadata={
                    "cwd": str(cwd),
                    "timeout_seconds": timeout_seconds,
                    "command": command,
                },
            )
        if outcome == "cancelled":
            return self._cancelled_result(
                command,
                cwd,
                timeout_seconds,
                stdout,
                stderr,
                emit_output,
                truncated=truncated,
            )

        parts = [f"exit_code: {running.process.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        result_cls = ToolResult.ok if running.process.returncode == 0 else ToolResult.error
        return result_cls(
            name=self.name,
            content="\n".join(parts),
            structured_content={
                "exit_code": running.process.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": truncated,
                "command": command,
                "command_name": self._command_name(command),
                "timed_out": False,
                "streaming": emit_output is not None,
            },
            metadata={"cwd": str(cwd), "timeout_seconds": timeout_seconds, "command": command},
        )

    def _cancelled_result(
        self,
        command: str,
        cwd,
        timeout_seconds: int | None,
        stdout: str,
        stderr: str,
        emit_output,
        *,
        truncated: bool = False,
    ) -> ToolResult:
        return ToolResult.error(
            name=self.name,
            content="Command cancelled",
            structured_content={
                "exit_code": None,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": truncated,
                "cancelled": True,
                "timed_out": False,
                "command": command,
                "streaming": emit_output is not None,
            },
            metadata={"cwd": str(cwd), "timeout_seconds": timeout_seconds, "command": command},
        )

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            process.wait()

    def _consume_stream(
        self,
        stream,
        stream_name: str,
        buffer: _BoundedTextBuffer,
        emit_output_holder: list[Any],
    ) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                buffer.append(line)
                emit_output = emit_output_holder[0]
                if emit_output is not None:
                    emit_output(
                        {
                            "tool_name": self.name,
                            "stream": stream_name,
                            "chunk": line,
                        }
                    )
        finally:
            stream.close()

    @staticmethod
    def _join_streams(running: _RunningCommand) -> None:
        deadline = time.monotonic() + 1
        for thread in (running.stdout_thread, running.stderr_thread):
            thread.join(timeout=max(0, deadline - time.monotonic()))

    @staticmethod
    def _combine_cancellation(*callbacks):
        active_callbacks = tuple(callback for callback in callbacks if callback is not None)
        return lambda: any(callback() for callback in active_callbacks)

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

        assessment = assess_bash_command(command)
        if assessment.action == "deny":
            return ToolResult.error(
                name=self.name,
                content=assessment.reason,
                structured_content={"command": command, "command_name": tokens[0]},
            )

        if re.search(r"\brm\s+-[^\n]*r[^\n]*f[^\n]*\s+(/|~)\b", command):
            return ToolResult.error(
                name=self.name,
                content="Destructive root-level delete commands are not allowed",
                structured_content={"command": command, "command_name": tokens[0]},
            )

        commands = assessment.commands or (tuple(tokens),)
        effective_cwd = cwd
        for words in commands:
            command_name = words[0]
            if command_name not in self._WORKSPACE_PATH_COMMANDS:
                continue
            if command_name == "cd":
                target = Path(words[1])
                if not target.is_absolute():
                    target = effective_cwd / target
                try:
                    effective_cwd = self._resolve_path(str(target))
                except ValueError as exc:
                    return ToolResult.error(
                        name=self.name,
                        content=str(exc),
                        structured_content={
                            "command": command,
                            "command_name": command_name,
                            "path": words[1],
                        },
                    )
                continue
            for token in words[1:]:
                if token.startswith("-") or token in {"!", "(", ")"}:
                    continue
                try:
                    self._resolve_command_path(token, effective_cwd)
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
