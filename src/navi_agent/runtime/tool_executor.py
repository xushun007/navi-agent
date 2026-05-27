from __future__ import annotations

import logging

from navi_agent.tooling import ToolContext, ToolPolicy, ToolResult
from navi_agent.tools.base import BaseTool

from .models import ToolCall

logger = logging.getLogger("navi_agent.runtime.tool_executor")


class ToolExecutor:
    def __init__(self, policy: ToolPolicy) -> None:
        self._policy = policy

    def execute(
        self,
        tool_calls: list[ToolCall],
        tools_by_name: dict[str, BaseTool],
        context: ToolContext | None = None,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for tool_call in tool_calls:
            tool = tools_by_name.get(tool_call.name)
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
                structured_content = {}
                if decision.requires_approval:
                    structured_content = {
                        "approval_required": True,
                        "tool_name": tool_call.name,
                        "arguments": tool_call.arguments,
                    }
                results.append(
                    ToolResult.error(
                        name=tool_call.name,
                        content=decision.reason or f"Tool blocked: {tool_call.name}",
                        structured_content=structured_content,
                        metadata=decision.metadata,
                    ).bind(tool_call.id)
                )
                continue

            try:
                output = tool.invoke(context=context, **tool_call.arguments)
                results.append(output.bind(tool_call.id, tool_call.name))
            except Exception as exc:
                logger.exception("Tool execution failed: %s", tool_call.name)
                results.append(
                    ToolResult.error(
                        name=tool_call.name,
                        content=f"Tool execution failed: {exc}",
                    ).bind(tool_call.id)
                )
        return results
