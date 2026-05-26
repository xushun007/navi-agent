from __future__ import annotations

from typing import Any

from navi_agent.tooling import ToolArtifact, ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class PatchTool(WorkspaceTool):
    @property
    def name(self) -> str:
        return "patch"

    @property
    def description(self) -> str:
        return "Apply a simple text replacement patch to a file."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        resolved = self._resolve_path(str(kwargs["path"]))
        current = resolved.read_text(encoding="utf-8")
        old = str(kwargs["old"])
        if old not in current:
            return ToolResult.error(
                name=self.name,
                content="patch_failed: target text not found",
                structured_content={"path": str(resolved.relative_to(self.root)), "applied": False},
            )
        updated = current.replace(old, str(kwargs["new"]), 1)
        resolved.write_text(updated, encoding="utf-8")
        return ToolResult.ok(
            name=self.name,
            content="patched: 1 replacement",
            structured_content={"path": str(resolved.relative_to(self.root)), "applied": True, "replacements": 1},
            artifacts=[
                ToolArtifact(
                    kind="file",
                    uri=str(resolved),
                    title=str(resolved.relative_to(self.root)),
                    mime_type="text/plain",
                )
            ],
        )
