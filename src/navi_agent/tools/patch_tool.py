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
                "replace_all": {"type": "boolean"},
                "expected_sha256": {"type": "string"},
            },
            "required": ["path", "old", "new"],
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
                content=f"Cannot patch binary file: {requested_path}",
                metadata={"path": requested_path},
            )
        current = resolved.read_text(encoding="utf-8")
        current_sha256 = self._sha256_text(current)
        expected_sha256 = kwargs.get("expected_sha256")
        if expected_sha256 and expected_sha256 != current_sha256:
            return ToolResult.error(
                name=self.name,
                content="patch rejected: file changed since last read",
                structured_content={
                    "path": str(resolved.relative_to(self.root)),
                    "current_sha256": current_sha256,
                    "expected_sha256": expected_sha256,
                    "applied": False,
                },
                metadata={"path": str(resolved)},
            )
        old = str(kwargs["old"])
        if not old:
            return ToolResult.error(name=self.name, content="Patch 'old' text must not be empty")
        if old not in current:
            return ToolResult.error(
                name=self.name,
                content="patch_failed: target text not found",
                structured_content={"path": str(resolved.relative_to(self.root)), "applied": False},
            )
        replacement_count = current.count(old)
        replace_all = bool(kwargs.get("replace_all", False))
        updated = current.replace(old, str(kwargs["new"]), replacement_count if replace_all else 1)
        resolved.write_text(updated, encoding="utf-8")
        replacements = replacement_count if replace_all else 1
        updated_sha256 = self._sha256_text(updated)
        return ToolResult.ok(
            name=self.name,
            content=f"patched: {replacements} replacement{'s' if replacements != 1 else ''}",
            structured_content={
                "path": str(resolved.relative_to(self.root)),
                "applied": True,
                "replacements": replacements,
                "replace_all": replace_all,
                "sha256": updated_sha256,
                "previous_sha256": current_sha256,
            },
            metadata={
                "path": str(resolved),
                "replacements": replacements,
                "replace_all": replace_all,
                "sha256": updated_sha256,
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
