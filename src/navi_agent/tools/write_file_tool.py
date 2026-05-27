from __future__ import annotations

from typing import Any

from navi_agent.tooling import ToolArtifact, ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class WriteFileTool(WorkspaceTool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write a text file inside the workspace."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        requested_path = str(kwargs["path"])
        try:
            resolved = self._resolve_path(requested_path)
        except ValueError as exc:
            return ToolResult.error(name=self.name, content=str(exc), metadata={"path": requested_path})
        if resolved.exists() and resolved.is_dir():
            return ToolResult.error(
                name=self.name,
                content=f"Path is a directory, not a file: {requested_path}",
                metadata={"path": requested_path},
            )
        existed = resolved.exists()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        content = str(kwargs["content"])
        resolved.write_text(content, encoding="utf-8")
        bytes_written = len(content.encode("utf-8"))
        return ToolResult.ok(
            name=self.name,
            content=f"bytes_written: {bytes_written}",
            structured_content={
                "path": str(resolved.relative_to(self.root)),
                "bytes_written": bytes_written,
                "existed": existed,
            },
            metadata={"path": str(resolved), "bytes_written": bytes_written, "existed": existed},
            artifacts=[
                ToolArtifact(
                    kind="file",
                    uri=str(resolved),
                    title=str(resolved.relative_to(self.root)),
                    mime_type="text/plain",
                )
            ],
        )
