from __future__ import annotations

from pathlib import Path

from navi_agent.memory import InMemoryMemoryStore, MemoryStore
from navi_agent.runtime import BackgroundTaskManager, ToolRegistry, ToolsetDefinition
from navi_agent.runtime.approval import ApprovalProvider
from navi_agent.runtime.tool_policy import SensitiveToolPolicy

from .bash_tool import BashTool
from .background_task_tool import BackgroundTaskTool
from .code_executor_tool import CodeExecutorTool
from .memory_tool import MemoryTool
from .patch_tool import PatchTool
from .read_file_tool import ReadFileTool
from .search_files_tool import SearchFilesTool
from .skill_view_tool import SkillListTool, SkillViewTool
from .todo_tool import TodoTool
from .write_file_tool import WriteFileTool


def build_default_tool_registry(
    root: Path | None = None,
    memory_store: MemoryStore | None = None,
    approval_provider: ApprovalProvider | None = None,
    skill_store=None,
    background_task_manager: BackgroundTaskManager | None = None,
) -> ToolRegistry:
    workspace_root = root or Path.cwd()
    shared_memory_store = memory_store or InMemoryMemoryStore()
    background_task_manager = background_task_manager or BackgroundTaskManager()
    return ToolRegistry(
        registered_tools=[
            (
                "terminal",
                BashTool(
                    root=workspace_root,
                    max_timeout_seconds=3600,
                    background_task_manager=background_task_manager,
                ),
            ),
            ("terminal", BackgroundTaskTool(background_task_manager)),
            ("code", CodeExecutorTool(root=workspace_root)),
            ("file", ReadFileTool(root=workspace_root)),
            ("file", SearchFilesTool(root=workspace_root)),
            ("file", WriteFileTool(root=workspace_root)),
            ("file", PatchTool(root=workspace_root)),
            ("memory", MemoryTool(memory_store=shared_memory_store)),
            *(
                [
                    ("skills", SkillListTool(skill_store=skill_store)),
                    ("skills", SkillViewTool(skill_store=skill_store)),
                ]
                if skill_store is not None
                else []
            ),
            ("todo", TodoTool()),
        ],
        toolsets=[
            ToolsetDefinition(name="terminal", tools=["bash", "background_task"]),
            ToolsetDefinition(name="code", tools=["code_executor"]),
            ToolsetDefinition(name="file", tools=["read_file", "search_files", "write_file", "patch"]),
            ToolsetDefinition(name="memory", tools=["memory"]),
            ToolsetDefinition(name="skills", tools=["skill_list", "skill_view"]),
            ToolsetDefinition(name="todo", tools=["todo"]),
            ToolsetDefinition(name="core", includes=["terminal", "code", "file", "memory", "skills", "todo"]),
        ],
        approval_provider=approval_provider,
        policy=SensitiveToolPolicy(
            approval_required_tools={
                "bash": "bash requires approval",
                "code_executor": "code_executor requires approval",
                "write_file": "write_file requires approval",
                "patch": "patch requires approval",
            }
        ),
    )
