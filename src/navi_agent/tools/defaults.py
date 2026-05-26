from __future__ import annotations

from pathlib import Path

from navi_agent.runtime import ToolRegistry, ToolsetDefinition

from .builtin import BashTool, ReadFileTool, SearchFilesTool


def build_default_tool_registry(root: Path | None = None) -> ToolRegistry:
    workspace_root = root or Path.cwd()
    return ToolRegistry(
        registered_tools=[
            ("terminal", BashTool(root=workspace_root)),
            ("file", ReadFileTool(root=workspace_root)),
            ("file", SearchFilesTool(root=workspace_root)),
        ],
        toolsets=[
            ToolsetDefinition(name="terminal", tools=["bash"]),
            ToolsetDefinition(name="file", tools=["read_file", "search_files"]),
            ToolsetDefinition(name="core", includes=["terminal", "file"]),
        ],
    )
