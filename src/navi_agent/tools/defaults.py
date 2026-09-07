from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from navi_agent.memory import InMemoryMemoryStore, MemoryStore
from navi_agent.paths import get_cron_jobs_path
from navi_agent.runtime import (
    BackgroundTaskManager,
    JsonPendingInteractionStore,
    SubagentService,
    ToolRegistration,
    ToolRegistry,
    ToolsetDefinition,
)
from navi_agent.runtime.tasks.cron import CronJobStore
from navi_agent.runtime.tools.approval import ApprovalProvider
from navi_agent.runtime.tools.policy import BashCommandPolicy, SensitiveToolPolicy

from .ask_user_tool import AskUserTool
from .base import BaseTool
from .bash_tool import BashTool
from .background_task_tool import BackgroundTaskTool
from .code_executor_tool import CodeExecutorTool
from .cron_tool import CronTool
from .delegate_task_tool import DelegateTaskTool
from .glob_tool import GlobTool
from .grep_tool import GrepTool
from .memory_tool import MemoryTool
from .patch_tool import PatchTool
from .read_file_tool import ReadFileTool
from .session_search_tool import SessionSearchTool
from .skill_view_tool import SkillListTool, SkillViewTool
from .todo_tool import TodoTool
from .write_file_tool import WriteFileTool
from .web_fetch_tool import WebFetchTool
from .web_search_tool import WebSearchTool


class BuiltinToolProvider:
    """Construct Navi's built-in tools without owning runtime policy."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        memory_store: MemoryStore | None = None,
        skill_store=None,
        background_task_manager: BackgroundTaskManager | None = None,
        subagent_service: SubagentService | None = None,
        session_store=None,
        additional_roots: Iterable[Path] | None = None,
        interaction_store: JsonPendingInteractionStore | None = None,
        web_search_api_key: str | None = None,
    ) -> None:
        self._root = root or Path.cwd()
        self._memory_store = memory_store or InMemoryMemoryStore()
        self._skill_store = skill_store
        self._background_task_manager = background_task_manager or BackgroundTaskManager()
        self._subagent_service = subagent_service
        self._session_store = session_store
        self._additional_roots = tuple(additional_roots or ())
        self._interaction_store = interaction_store
        self._web_search_api_key = web_search_api_key

    def load_tools(self) -> tuple[ToolRegistration, ...]:
        registrations = [
            self._registration(
                "terminal",
                BashTool(
                    root=self._root,
                    default_timeout_seconds=3600,
                    max_timeout_seconds=3600,
                    background_task_manager=self._background_task_manager,
                    additional_roots=self._additional_roots,
                ),
            ),
            self._registration(
                "terminal", BackgroundTaskTool(self._background_task_manager)
            ),
            self._registration(
                "code",
                CodeExecutorTool(root=self._root, additional_roots=self._additional_roots),
            ),
            self._registration(
                "file",
                ReadFileTool(root=self._root, additional_roots=self._additional_roots),
            ),
            self._registration(
                "file",
                GlobTool(root=self._root, additional_roots=self._additional_roots),
            ),
            self._registration(
                "file",
                GrepTool(root=self._root, additional_roots=self._additional_roots),
            ),
            self._registration(
                "file",
                WriteFileTool(root=self._root, additional_roots=self._additional_roots),
            ),
            self._registration(
                "file",
                PatchTool(root=self._root, additional_roots=self._additional_roots),
            ),
            self._registration("memory", MemoryTool(memory_store=self._memory_store)),
            self._registration(
                "scheduler", CronTool(store=CronJobStore(get_cron_jobs_path()))
            ),
            self._registration("todo", TodoTool()),
            self._registration("web", WebFetchTool()),
            self._registration("web", WebSearchTool(api_key=self._web_search_api_key)),
        ]
        if self._session_store is not None:
            registrations.append(
                self._registration("session", SessionSearchTool(self._session_store))
            )
        if self._subagent_service is not None:
            registrations.append(
                self._registration("delegation", DelegateTaskTool(self._subagent_service))
            )
        if self._skill_store is not None:
            registrations.extend(
                [
                    self._registration(
                        "skills", SkillListTool(skill_store=self._skill_store)
                    ),
                    self._registration(
                        "skills", SkillViewTool(skill_store=self._skill_store)
                    ),
                ]
            )
        if self._interaction_store is not None:
            registrations.append(
                self._registration("interaction", AskUserTool(self._interaction_store))
            )
        return tuple(registrations)

    def close(self) -> None:
        return None

    @staticmethod
    def _registration(toolset: str, tool: BaseTool) -> ToolRegistration:
        return ToolRegistration(tool=tool, toolsets=(toolset,), source="builtin")


def build_tool_registry(
    registrations: Iterable[ToolRegistration],
    *,
    approval_provider: ApprovalProvider | None = None,
) -> ToolRegistry:
    resolved_registrations = tuple(registrations)
    registry = ToolRegistry(
        toolsets=_default_toolsets(resolved_registrations),
        approval_provider=approval_provider,
        policy=BashCommandPolicy(
            fallback=SensitiveToolPolicy(
                approval_required_tools={
                    "code_executor": "code_executor requires approval",
                    "write_file": "write_file requires approval",
                    "patch": "patch requires approval",
                }
            )
        ),
    )
    for registration in resolved_registrations:
        registry.register_tool(registration.tool, toolsets=list(registration.toolsets))
    return registry


def build_default_tool_registry(
    root: Path | None = None,
    memory_store: MemoryStore | None = None,
    approval_provider: ApprovalProvider | None = None,
    skill_store=None,
    background_task_manager: BackgroundTaskManager | None = None,
    subagent_service: SubagentService | None = None,
    session_store=None,
    additional_roots: Iterable[Path] | None = None,
    interaction_store: JsonPendingInteractionStore | None = None,
    web_search_api_key: str | None = None,
    mcp_tools: Iterable[BaseTool] | None = None,
) -> ToolRegistry:
    provider = BuiltinToolProvider(
        root=root,
        memory_store=memory_store,
        skill_store=skill_store,
        background_task_manager=background_task_manager,
        subagent_service=subagent_service,
        session_store=session_store,
        additional_roots=additional_roots,
        interaction_store=interaction_store,
        web_search_api_key=web_search_api_key,
    )
    resolved_mcp_tools = tuple(mcp_tools or ())
    registrations = [
        *provider.load_tools(),
        *(
            ToolRegistration(tool=tool, toolsets=("mcp",), source="mcp")
            for tool in resolved_mcp_tools
        ),
    ]
    return build_tool_registry(registrations, approval_provider=approval_provider)


def _default_toolsets(
    registrations: Iterable[ToolRegistration],
) -> list[ToolsetDefinition]:
    mcp_names = [
        registration.tool.name
        for registration in registrations
        if "mcp" in registration.toolsets
    ]
    return [
        ToolsetDefinition(name="terminal", tools=["bash", "background_task"]),
        ToolsetDefinition(name="code", tools=["code_executor"]),
        ToolsetDefinition(
            name="file",
            tools=["read_file", "glob", "grep", "write_file", "patch"],
        ),
        ToolsetDefinition(name="memory", tools=["memory"]),
        ToolsetDefinition(name="session", tools=["session_search"]),
        ToolsetDefinition(name="scheduler", tools=["cron"]),
        ToolsetDefinition(name="delegation", tools=["delegate_task"]),
        ToolsetDefinition(name="skills", tools=["skill_list", "skill_view"]),
        ToolsetDefinition(name="todo", tools=["todo"]),
        ToolsetDefinition(name="web", tools=["web_search", "web_fetch"]),
        ToolsetDefinition(name="mcp", tools=mcp_names),
        ToolsetDefinition(name="interaction", tools=["ask_user"]),
        ToolsetDefinition(
            name="core",
            includes=[
                "terminal",
                "code",
                "file",
                "memory",
                "session",
                "skills",
                "todo",
                "scheduler",
                "delegation",
                "interaction",
                "web",
                "mcp",
            ],
        ),
    ]
