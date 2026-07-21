from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from navi_agent.tooling import ToolArtifact, ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class ReadFileTool(WorkspaceTool):
    def __init__(
        self,
        root=None,
        default_line_count: int = 200,
        max_line_count: int = 500,
        additional_roots: Iterable[Path] | None = None,
    ) -> None:
        super().__init__(root=root, additional_roots=additional_roots)
        self._default_line_count = default_line_count
        self._max_line_count = max_line_count

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read a text file from the workspace or an explicitly added directory."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "line_count": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        requested_path = str(kwargs["path"])
        try:
            resolved = self._resolve_path(requested_path)
        except ValueError as exc:
            return ToolResult.error(name=self.name, content=str(exc), metadata={"path": requested_path})
        if not resolved.exists():
            return ToolResult.error(name=self.name, **self._missing_path_error(requested_path))
        if resolved.is_dir():
            return ToolResult.error(
                name=self.name,
                content=f"Path is a directory, not a file: {requested_path}",
                metadata={"path": requested_path},
            )
        if self._is_binary_file(resolved):
            return ToolResult.error(
                name=self.name,
                content=f"Cannot read binary file: {requested_path}",
                metadata={"path": requested_path},
            )

        lines = resolved.read_text(encoding="utf-8").splitlines()
        start_line = max(1, int(kwargs.get("start_line", 1)))
        requested_line_count = int(kwargs.get("line_count", self._default_line_count))
        line_count = max(1, min(requested_line_count, self._max_line_count))
        end_index = start_line - 1 + line_count
        selected = lines[start_line - 1 : end_index]
        content = "\n".join(
            f"{line_number}: {line_content}"
            for line_number, line_content in enumerate(selected, start=start_line)
        )
        truncated = end_index < len(lines)
        next_start_line = start_line + len(selected) if truncated else None
        if truncated:
            content += f"\n\nFile has more lines. Continue with start_line={next_start_line}."
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "path": self._display_path(resolved),
                "start_line": start_line,
                "requested_line_count": requested_line_count,
                "line_count": len(selected),
                "total_lines": len(lines),
                "truncated": truncated,
                "next_start_line": next_start_line,
            },
            artifacts=[
                ToolArtifact(
                    kind="file",
                    uri=str(resolved),
                    title=self._display_path(resolved),
                    mime_type="text/plain",
                )
            ],
        )
