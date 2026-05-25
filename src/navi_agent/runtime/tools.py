from __future__ import annotations

from collections.abc import Callable

from .models import ToolCall, ToolResult

ToolHandler = Callable[..., str]


class ToolRegistry:
    def __init__(self, tools: dict[str, ToolHandler] | None = None) -> None:
        self._tools = tools or {}

    def schemas(self) -> list[dict[str, str]]:
        return [{"name": name} for name in sorted(self._tools)]

    def dispatch(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        results = []
        for tool_call in tool_calls:
            handler = self._tools.get(tool_call.name)
            if handler is None:
                raise KeyError(f"Unknown tool: {tool_call.name}")
            output = handler(**tool_call.arguments)
            results.append(
                ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=str(output),
                )
            )
        return results
