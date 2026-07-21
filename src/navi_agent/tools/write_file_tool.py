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
        return "Write a text file inside the workspace or an explicitly added directory."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "expected_sha256": {"type": "string"},
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
        current_sha256 = None
        expected_sha256 = kwargs.get("expected_sha256")
        if existed:
            current_content = resolved.read_text(encoding="utf-8")
            current_sha256 = self._sha256_text(current_content)
            if expected_sha256 and expected_sha256 != current_sha256:
                return ToolResult.error(
                    name=self.name,
                    content="write_file rejected: file changed since last read",
                    structured_content={
                        "path": self._display_path(resolved),
                        "current_sha256": current_sha256,
                        "expected_sha256": expected_sha256,
                    },
                    metadata={"path": str(resolved)},
                )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        content = str(kwargs["content"])
        resolved.write_text(content, encoding="utf-8")
        bytes_written = len(content.encode("utf-8"))
        written_sha256 = self._sha256_text(content)
        return ToolResult.ok(
            name=self.name,
            content=f"bytes_written: {bytes_written}",
            structured_content={
                "path": self._display_path(resolved),
                "bytes_written": bytes_written,
                "existed": existed,
                "sha256": written_sha256,
                "previous_sha256": current_sha256,
            },
            metadata={
                "path": str(resolved),
                "bytes_written": bytes_written,
                "existed": existed,
                "sha256": written_sha256,
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
