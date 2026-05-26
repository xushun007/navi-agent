from __future__ import annotations

import fnmatch
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class SearchFilesTool(WorkspaceTool):
    def __init__(self, root=None, max_matches: int = 50) -> None:
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

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
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
                        return ToolResult.ok(
                            name=self.name,
                            content="\n".join(matches),
                            structured_content={"matches": matches, "truncated": True},
                        )
        return ToolResult.ok(
            name=self.name,
            content="\n".join(matches),
            structured_content={"matches": matches, "truncated": False},
        )
