from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable
import logging
import inspect

from .models import ToolCall, ToolContext, ToolResult

ToolHandler = Callable[..., str]
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
        toolsets: list[ToolsetDefinition] | None = None,
    ) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._toolsets: dict[str, ToolsetDefinition] = {
            toolset.name: toolset for toolset in (toolsets or [])
        }

        for definition in definitions or []:
            self._definitions[definition.name] = definition

        for name, handler in (tools or {}).items():
            self._definitions[name] = ToolDefinition(name=name, handler=handler)

    def schemas(
        self,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters,
            }
            for definition in sorted(
                self._select_definitions(
                    enabled_toolsets=enabled_toolsets,
                    disabled_toolsets=disabled_toolsets,
                ),
                key=lambda item: item.name,
            )
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
            definition.name
            for definition in self._select_definitions(
                enabled_toolsets=enabled_toolsets,
                disabled_toolsets=disabled_toolsets,
            )
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
            definition = self._definitions.get(tool_call.name)
            if definition is None:
                results.append(
                    ToolResult(
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=f"Unknown tool: {tool_call.name}",
                        status="error",
                    )
                )
                continue
            try:
                output = self._invoke_handler(definition, tool_call.arguments, context)
                status = "success"
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

    def _invoke_handler(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolContext | None,
    ) -> str:
        if context is None:
            return definition.handler(**arguments)

        signature = inspect.signature(definition.handler)
        if "context" in signature.parameters:
            return definition.handler(context=context, **arguments)
        return definition.handler(**arguments)

    def _select_definitions(
        self,
        enabled_toolsets: list[str] | None,
        disabled_toolsets: list[str] | None,
    ) -> list[ToolDefinition]:
        definitions = list(self._definitions.values())
        if not enabled_toolsets and not disabled_toolsets:
            return definitions

        enabled_names = self._resolve_enabled_tool_names(enabled_toolsets)
        disabled_names = self._resolve_enabled_tool_names(disabled_toolsets)

        selected: list[ToolDefinition] = []
        for definition in definitions:
            if enabled_names and definition.name not in enabled_names:
                continue
            if definition.name in disabled_names:
                continue
            selected.append(definition)
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
            for definition in self._definitions.values():
                if definition.toolset == toolset_name:
                    resolved.add(definition.name)
            return

        resolved.update(toolset.tools)
        for included in toolset.includes:
            self._collect_toolset_tools(included, resolved, seen)
