from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

from .models import ToolCall, ToolResult

ToolHandler = Callable[..., str]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    handler: ToolHandler
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
    )


class ToolRegistry:
    def __init__(
        self,
        tools: dict[str, ToolHandler] | None = None,
        definitions: list[ToolDefinition] | None = None,
    ) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

        for definition in definitions or []:
            self._definitions[definition.name] = definition

        for name, handler in (tools or {}).items():
            self._definitions[name] = ToolDefinition(name=name, handler=handler)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters,
            }
            for definition in sorted(
                self._definitions.values(),
                key=lambda item: item.name,
            )
        ]

    def dispatch(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        results = []
        for tool_call in tool_calls:
            definition = self._definitions.get(tool_call.name)
            if definition is None:
                raise KeyError(f"Unknown tool: {tool_call.name}")
            output = definition.handler(**tool_call.arguments)
            results.append(
                ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=str(output),
                )
            )
        return results
