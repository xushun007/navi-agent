from __future__ import annotations

from typing import Any

from navi_agent.tooling import ToolArtifact, ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


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
                "line_count": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        resolved = self._resolve_path(str(kwargs["path"]))
        lines = resolved.read_text(encoding="utf-8").splitlines()
        start_line = max(1, int(kwargs.get("start_line", 1)))
        line_count = max(1, int(kwargs.get("line_count", len(lines))))
        end_index = start_line - 1 + line_count
        selected = lines[start_line - 1 : end_index]
        content = "\n".join(
            f"{line_number}: {line_content}"
            for line_number, line_content in enumerate(selected, start=start_line)
        )
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "path": str(resolved.relative_to(self.root)),
                "start_line": start_line,
                "requested_line_count": line_count,
                "line_count": len(selected),
            },
            artifacts=[
                ToolArtifact(
                    kind="file",
                    uri=str(resolved),
                    title=str(resolved.relative_to(self.root)),
                    mime_type="text/plain",
                )
            ],
        )
