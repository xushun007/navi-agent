from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
import subprocess
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .ripgrep import default_exclude_arguments, run_ripgrep
from .workspace_tool import WorkspaceTool


class GrepTool(WorkspaceTool):
    def __init__(
        self,
        root=None,
        max_matches: int = 100,
        max_line_length: int = 240,
        additional_roots: Iterable[Path] | None = None,
    ) -> None:
        super().__init__(root=root, additional_roots=additional_roots)
        self._max_matches = max_matches
        self._max_line_length = max_line_length

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents with a regular expression in the workspace or "
            "an explicitly added directory."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional file or directory inside an allowed root.",
                },
                "include": {
                    "type": "string",
                    "description": 'Optional file glob, for example "*.py".',
                },
            },
            "required": ["pattern"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        pattern = str(kwargs.get("pattern") or "").strip()
        if not pattern:
            return ToolResult.error(name=self.name, content="pattern is required")
        requested_path = kwargs.get("path")
        try:
            search_path = self._resolve_path(requested_path)
        except ValueError as exc:
            return ToolResult.error(
                name=self.name,
                content=str(exc),
                metadata={"path": requested_path},
            )
        if not search_path.exists():
            return ToolResult.error(
                name=self.name,
                **self._missing_path_error(str(requested_path)),
            )

        arguments = [
            "--json",
            "--hidden",
            *default_exclude_arguments(),
        ]
        include = str(kwargs.get("include") or "").strip()
        if include:
            arguments.extend(["--glob", include])
        arguments.extend(["--", pattern, str(search_path)])
        try:
            process = run_ripgrep(arguments, cwd=self.root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ToolResult.error(name=self.name, content=str(exc))
        if process.returncode not in {0, 1}:
            message = self._ripgrep_error(process.stderr)
            return ToolResult.error(name=self.name, content=message)

        matches = self._parse_matches(process.stdout)
        matches.sort(
            key=lambda match: self._mtime(str(match["path"])),
            reverse=True,
        )
        truncated = len(matches) > self._max_matches
        selected = matches[: self._max_matches]
        content = "\n".join(
            f"{match['path']}:{match['line_number']}: {match['line']}"
            for match in selected
        )
        if not content:
            content = "No matches found"
        if truncated:
            content += "\n\nResults truncated. Use a narrower path or pattern."
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "pattern": pattern,
                "include": include or None,
                "matches": selected,
                "match_count": len(selected),
                "truncated": truncated,
            },
        )

    def _parse_matches(self, output: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for raw_line in output.splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data") or {}
            raw_path = str((data.get("path") or {}).get("text") or "")
            line_number = data.get("line_number")
            line = str((data.get("lines") or {}).get("text") or "").rstrip("\r\n")
            if not raw_path or not isinstance(line_number, int):
                continue
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.root / path
            preview = (
                line
                if len(line) <= self._max_line_length
                else line[: self._max_line_length] + "..."
            )
            matches.append(
                {
                    "path": self._display_path(path),
                    "line_number": line_number,
                    "line": preview,
                }
            )
        return matches

    def _mtime(self, display_path: str) -> float:
        path = Path(display_path)
        if not path.is_absolute():
            path = self.root / path
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _ripgrep_error(stderr: str) -> str:
        detail = stderr.strip()
        return f"ripgrep failed: {detail}" if detail else "ripgrep failed"
