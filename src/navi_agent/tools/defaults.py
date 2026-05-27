from __future__ import annotations

from pathlib import Path

from navi_agent.memory import InMemoryMemoryStore
from navi_agent.runtime import ToolRegistry, ToolsetDefinition
from navi_agent.runtime.tool_policy import StaticToolPolicy

from .bash_tool import BashTool
from .memory_tool import MemoryTool
from .patch_tool import PatchTool
from .read_file_tool import ReadFileTool
from .search_files_tool import SearchFilesTool
from .write_file_tool import WriteFileTool


def build_default_tool_registry(
    root: Path | None = None,
    memory_store: InMemoryMemoryStore | None = None,
) -> ToolRegistry:
    workspace_root = root or Path.cwd()
    shared_memory_store = memory_store or InMemoryMemoryStore()
    return ToolRegistry(
        registered_tools=[
            ("terminal", BashTool(root=workspace_root)),
            ("file", ReadFileTool(root=workspace_root)),
            ("file", SearchFilesTool(root=workspace_root)),
            ("file", WriteFileTool(root=workspace_root)),
            ("file", PatchTool(root=workspace_root)),
            ("memory", MemoryTool(memory_store=shared_memory_store)),
        ],
        toolsets=[
            ToolsetDefinition(name="terminal", tools=["bash"]),
            ToolsetDefinition(name="file", tools=["read_file", "search_files", "write_file", "patch"]),
            ToolsetDefinition(name="memory", tools=["memory"]),
            ToolsetDefinition(name="core", includes=["terminal", "file", "memory"]),
        ],
        policy=StaticToolPolicy(
            denied_tools={
                "bash": "bash requires approval",
                "write_file": "write_file requires approval",
                "patch": "patch requires approval",
            }
        ),
    )
