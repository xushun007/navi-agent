from __future__ import annotations

from pathlib import Path

from navi_agent.tools.base import BaseTool

from ..models import ToolCall


PARALLEL_SAFE_TOOLS = frozenset(
    {
        "read_file",
        "search_files",
        "session_search",
        "skill_list",
        "skill_view",
    }
)
PATH_SCOPED_TOOLS = frozenset({"read_file", "write_file", "patch"})
NEVER_PARALLEL_TOOLS = frozenset({"ask_user"})


def should_run_tools_concurrently(
    tool_calls: list[ToolCall],
    tools_by_name: dict[str, BaseTool],
) -> bool:
    """Return whether a complete tool-call batch is safe to run concurrently."""
    if len(tool_calls) <= 1:
        return False
    if any(tool_call.name in NEVER_PARALLEL_TOOLS for tool_call in tool_calls):
        return False

    reserved_paths: list[Path] = []
    for tool_call in tool_calls:
        tool = tools_by_name.get(tool_call.name)
        if tool is None:
            return False

        if tool_call.name in PATH_SCOPED_TOOLS:
            scoped_path = _parallel_scope_path(tool, tool_call.arguments)
            if scoped_path is None:
                return False
            if any(_paths_overlap(scoped_path, existing) for existing in reserved_paths):
                return False
            reserved_paths.append(scoped_path)
            continue

        if tool_call.name not in PARALLEL_SAFE_TOOLS:
            return False

    return True


def _parallel_scope_path(tool: BaseTool, arguments: dict[str, object]) -> Path | None:
    raw_path = arguments.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        root = getattr(tool, "root", Path.cwd())
        path = Path(root) / path
    return path.resolve(strict=False)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)
