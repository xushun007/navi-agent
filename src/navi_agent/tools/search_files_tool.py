from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .workspace_tool import WorkspaceTool


class SearchFilesTool(WorkspaceTool):
    def __init__(
        self,
        root=None,
        max_matches: int = 50,
        max_line_length: int = 240,
        additional_roots: Iterable[Path] | None = None,
    ) -> None:
        super().__init__(root=root, additional_roots=additional_roots)
        self._max_matches = max_matches
        self._max_line_length = max_line_length

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return "Search files in the workspace or an explicitly added directory. Use query as the search term."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term or regex pattern."},
                "path": {"type": "string", "description": "Optional base path inside an allowed directory."},
                "glob": {"type": "string", "description": "Optional filename glob filter."},
                "search_mode": {
                    "type": "string",
                    "enum": ["content", "filename", "regex"],
                    "description": "Search content, filenames, or treat query as a regex.",
                },
            },
            "required": ["query"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        query_value = kwargs.get("query")
        if query_value is None:
            return ToolResult.error(name=self.name, content="Missing required argument: query")
        query = str(query_value).strip()
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
        if search_mode not in {"content", "filename", "regex"}:
            return ToolResult.error(
                name=self.name,
                content=f"Unsupported search_mode: {search_mode}",
            )
        regex = None
        if search_mode == "regex":
            try:
                regex = re.compile(query)
            except re.error as exc:
                return ToolResult.error(
                    name=self.name,
                    content=f"Invalid regex pattern: {exc}",
                )
        matches: list[str] = []
        structured_matches: list[dict[str, Any]] = []

        for path in sorted(base_path.rglob("*")):
            if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
                continue
            display_path = self._display_path(path)
            if search_mode == "filename":
                if query in path.name:
                    matches.append(display_path)
                    structured_matches.append({"path": display_path})
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
                matched = bool(regex.search(line)) if regex is not None else query in line
                if matched:
                    preview = line if len(line) <= self._max_line_length else line[: self._max_line_length] + "..."
                    matches.append(f"{display_path}:{line_number}: {preview}")
                    structured_matches.append(
                        {
                            "path": display_path,
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
