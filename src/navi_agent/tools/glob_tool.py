from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import subprocess
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .ripgrep import default_exclude_arguments, run_ripgrep
from .workspace_tool import WorkspaceTool


class GlobTool(WorkspaceTool):
    def __init__(
        self,
        root=None,
        max_results: int = 100,
        additional_roots: Iterable[Path] | None = None,
    ) -> None:
        super().__init__(root=root, additional_roots=additional_roots)
        self._max_results = max_results

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files by glob pattern in the workspace or an explicitly added "
            "directory. Supports patterns such as **/*.py and src/**/*.ts."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern matched against file paths.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional base directory inside an allowed root.",
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
            base_path = self._resolve_path(requested_path)
        except ValueError as exc:
            return ToolResult.error(
                name=self.name,
                content=str(exc),
                metadata={"path": requested_path},
            )
        if not base_path.exists():
            return ToolResult.error(
                name=self.name,
                **self._missing_path_error(str(requested_path)),
            )
        if not base_path.is_dir():
            return ToolResult.error(
                name=self.name,
                content=f"Path is not a directory: {requested_path}",
            )
        try:
            process = run_ripgrep(
                [
                    "--files",
                    "--hidden",
                    *default_exclude_arguments(),
                    "--glob",
                    pattern,
                ],
                cwd=base_path,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ToolResult.error(name=self.name, content=str(exc))
        if process.returncode not in {0, 1}:
            return ToolResult.error(
                name=self.name,
                content=f"ripgrep failed: {process.stderr.strip()}",
            )

        raw_paths = [
            self._display_path((base_path / raw_path).resolve())
            for raw_path in process.stdout.splitlines()
            if raw_path.strip()
        ]
        truncated = len(raw_paths) > self._max_results
        paths = raw_paths[: self._max_results]
        paths = sorted(
            paths,
            key=lambda path: self._mtime(path),
            reverse=True,
        )
        content = "\n".join(paths) if paths else "No files found"
        if truncated:
            content += "\n\nResults truncated. Use a narrower path or pattern."
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "pattern": pattern,
                "paths": paths,
                "count": len(paths),
                "truncated": truncated,
            },
        )

    def _mtime(self, display_path: str) -> float:
        path = Path(display_path)
        if not path.is_absolute():
            path = self.root / path
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0
