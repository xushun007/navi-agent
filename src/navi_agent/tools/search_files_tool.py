from __future__ import annotations

import fnmatch
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class SearchFilesTool(WorkspaceTool):
    def __init__(self, root=None, max_matches: int = 50, max_line_length: int = 240) -> None:
        super().__init__(root=root)
        self._max_matches = max_matches
        self._max_line_length = max_line_length

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
                "search_mode": {
                    "type": "string",
                    "enum": ["content", "filename"],
                },
            },
            "required": ["query"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        query = str(kwargs["query"]).strip()
        if not query:
            return ToolResult.error(name=self.name, content="Search query must not be empty")
        requested_path = kwargs.get("path")
        try:
            base_path = self._resolve_path(requested_path)
        except ValueError as exc:
            return ToolResult.error(name=self.name, content=str(exc), metadata={"path": requested_path})
        if not base_path.exists():
            return ToolResult.error(name=self.name, **self._missing_path_error(str(requested_path)))
        pattern = str(kwargs.get("glob", "*"))
        search_mode = str(kwargs.get("search_mode", "content"))
        if search_mode not in {"content", "filename"}:
            return ToolResult.error(
                name=self.name,
                content=f"Unsupported search_mode: {search_mode}",
            )
        matches: list[str] = []
        structured_matches: list[dict[str, Any]] = []

        for path in sorted(base_path.rglob("*")):
            if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
                continue
            rel_path = path.relative_to(self.root)
            if search_mode == "filename":
                if query in path.name:
                    matches.append(str(rel_path))
                    structured_matches.append({"path": str(rel_path)})
                    if len(matches) >= self._max_matches:
                        return ToolResult.ok(
                            name=self.name,
                            content="\n".join(matches),
                            structured_content={
                                "query": query,
                                "search_mode": search_mode,
                                "matches": structured_matches,
                                "match_count": len(structured_matches),
                                "truncated": True,
                            },
                        )
                continue
            if self._is_binary_file(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if query in line:
                    preview = line if len(line) <= self._max_line_length else line[: self._max_line_length] + "..."
                    matches.append(f"{rel_path}:{line_number}: {preview}")
                    structured_matches.append(
                        {
                            "path": str(rel_path),
                            "line_number": line_number,
                            "line": preview,
                        }
                    )
                    if len(matches) >= self._max_matches:
                        return ToolResult.ok(
                            name=self.name,
                            content="\n".join(matches),
                            structured_content={
                                "query": query,
                                "search_mode": search_mode,
                                "matches": structured_matches,
                                "match_count": len(structured_matches),
                                "truncated": True,
                            },
                        )
        return ToolResult.ok(
            name=self.name,
            content="\n".join(matches),
            structured_content={
                "query": query,
                "search_mode": search_mode,
                "matches": structured_matches,
                "match_count": len(structured_matches),
                "truncated": False,
            },
        )
