from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

from navi_agent.runtime.models import ToolContext

from .base import BaseTool


class WorkspaceTool(BaseTool):
    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path.cwd()).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve_path(self, path: str | None = None) -> Path:
        target = self.root if not path else (self.root / path if not Path(path).is_absolute() else Path(path))
        resolved = target.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path is outside workspace: {resolved}") from exc
        return resolved


class BashTool(WorkspaceTool):
    def __init__(self, root: Path | None = None, default_timeout_seconds: int = 20) -> None:
        super().__init__(root=root)
        self._default_timeout_seconds = default_timeout_seconds

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

    def invoke(
        self,
        context: ToolContext | None = None,
        **kwargs: Any,
    ) -> str:
        command = str(kwargs["command"])
        timeout_seconds = int(kwargs.get("timeout_seconds", self._default_timeout_seconds))
        timeout_seconds = max(1, min(timeout_seconds, 60))
        try:
            cwd = self._resolve_path(kwargs.get("cwd"))
        except ValueError as exc:
            return str(exc)

        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        parts = [f"exit_code: {completed.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        return "\n".join(parts)


class ReadFileTool(WorkspaceTool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read a text file from the workspace."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> str:
        resolved = self._resolve_path(str(kwargs["path"]))
        lines = resolved.read_text(encoding="utf-8").splitlines()
        start_line = max(1, int(kwargs.get("start_line", 1)))
        end_line = int(kwargs.get("end_line", len(lines)))
        selected = lines[start_line - 1 : end_line]
        return "\n".join(
            f"{line_number}: {content}"
            for line_number, content in enumerate(selected, start=start_line)
        )


class SearchFilesTool(WorkspaceTool):
    def __init__(self, root: Path | None = None, max_matches: int = 50) -> None:
        super().__init__(root=root)
        self._max_matches = max_matches

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return "Search text across workspace files."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string"},
            },
            "required": ["query"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> str:
        query = str(kwargs["query"])
        base_path = self._resolve_path(kwargs.get("path"))
        pattern = str(kwargs.get("glob", "*"))
        matches: list[str] = []

        for path in sorted(base_path.rglob("*")):
            if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            rel_path = path.relative_to(self.root)
            for line_number, line in enumerate(lines, start=1):
                if query in line:
                    matches.append(f"{rel_path}:{line_number}: {line}")
                    if len(matches) >= self._max_matches:
                        return "\n".join(matches)
        return "\n".join(matches)
