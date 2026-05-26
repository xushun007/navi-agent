from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable
import logging

from navi_agent.tooling import ToolContext, ToolPolicy, ToolResult

from .models import ToolCall
from .tool_policy import AllowAllToolPolicy
from navi_agent.tools.base import BaseTool, FunctionTool

ToolHandler = Callable[..., ToolResult]
logger = logging.getLogger("navi_agent.runtime.tools")


@dataclass(slots=True)
class ToolDefinition:
    name: str
    handler: ToolHandler
    description: str = ""
    toolset: str = "default"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
    )


@dataclass(slots=True)
class ToolsetDefinition:
    name: str
    tools: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    description: str = ""


class ToolRegistry:
    def __init__(
        self,
        tools: dict[str, ToolHandler] | None = None,
        definitions: list[ToolDefinition] | None = None,
        registered_tools: list[tuple[str, BaseTool]] | None = None,
        toolsets: list[ToolsetDefinition] | None = None,
        policy: ToolPolicy | None = None,
    ) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._toolsets_by_tool: dict[str, set[str]] = {}
        self._toolsets: dict[str, ToolsetDefinition] = {
            toolset.name: toolset for toolset in (toolsets or [])
        }
        self._policy = policy or AllowAllToolPolicy()

        for definition in definitions or []:
            self.register_tool(
                FunctionTool(
                    name=definition.name,
                    description=definition.description,
                    handler=definition.handler,
                    parameters=definition.parameters,
                ),
                toolsets=[definition.toolset],
            )

        for name, handler in (tools or {}).items():
            self.register_tool(
                FunctionTool(
                    name=name,
                    description="",
                    handler=handler,
                ),
                toolsets=["default"],
            )

        for toolset_name, tool in registered_tools or []:
            self.register_tool(tool, toolsets=[toolset_name])

    def register_tool(self, tool: BaseTool, toolsets: list[str]) -> None:
        self._tools[tool.name] = tool
        self._toolsets_by_tool[tool.name] = set(toolsets)

    def schemas(
        self,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.schema(),
            }
            for tool in sorted(
                self._select_tools(
                    enabled_toolsets=enabled_toolsets,
                    disabled_toolsets=disabled_toolsets,
                ),
                key=lambda item: item.name,
            )
            if tool.is_available()
        ]

    def dispatch(
        self,
        tool_calls: list[ToolCall],
        context: ToolContext | None = None,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> list[ToolResult]:
        results = []
        allowed_names = {
            tool.name
            for tool in self._select_tools(
                enabled_toolsets=enabled_toolsets,
                disabled_toolsets=disabled_toolsets,
            )
            if tool.is_available()
        }
        for tool_call in tool_calls:
            if allowed_names and tool_call.name not in allowed_names:
                results.append(
                    ToolResult(
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=f"Tool not enabled: {tool_call.name}",
                        status="error",
                    )
                )
                continue
            tool = self._tools.get(tool_call.name)
            if tool is None:
                results.append(
                    ToolResult.error(
                        name=tool_call.name,
                        content=f"Unknown tool: {tool_call.name}",
                    ).bind(tool_call.id)
                )
                continue
            decision = self._policy.decide(tool_call.name, tool_call.arguments, context)
            if not decision.allows_execution:
                results.append(
                    ToolResult.error(
                        name=tool_call.name,
                        content=decision.reason or f"Tool blocked: {tool_call.name}",
                        metadata=decision.metadata,
                    ).bind(tool_call.id)
                )
                continue
            try:
                output = tool.invoke(context=context, **tool_call.arguments)
                results.append(output.bind(tool_call.id, tool_call.name))
                continue
            except Exception as exc:
                logger.exception("Tool execution failed: %s", tool_call.name)
                output = f"Tool execution failed: {exc}"
                status = "error"
            results.append(
                ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=str(output),
                    status=status,
                )
            )
        return results

    def _select_tools(
        self,
        enabled_toolsets: list[str] | None,
        disabled_toolsets: list[str] | None,
    ) -> list[BaseTool]:
        tools = list(self._tools.values())
        if not enabled_toolsets and not disabled_toolsets:
            return tools

        enabled_names = self._resolve_enabled_tool_names(enabled_toolsets)
        disabled_names = self._resolve_enabled_tool_names(disabled_toolsets)

        selected: list[BaseTool] = []
        for tool in tools:
            if enabled_names and tool.name not in enabled_names:
                continue
            if tool.name in disabled_names:
                continue
            selected.append(tool)
        return selected

    def _resolve_enabled_tool_names(self, toolsets: list[str] | None) -> set[str]:
        if not toolsets:
            return set()

        resolved: set[str] = set()
        for toolset_name in toolsets:
            self._collect_toolset_tools(toolset_name, resolved, seen=set())
        return resolved

    def _collect_toolset_tools(
        self,
        toolset_name: str,
        resolved: set[str],
        seen: set[str],
    ) -> None:
        if toolset_name in seen:
            return
        seen.add(toolset_name)

        toolset = self._toolsets.get(toolset_name)
        if toolset is None:
            for tool_name, tool_toolsets in self._toolsets_by_tool.items():
                if toolset_name in tool_toolsets:
                    resolved.add(tool_name)
            return

        resolved.update(toolset.tools)
        for included in toolset.includes:
            self._collect_toolset_tools(included, resolved, seen)
