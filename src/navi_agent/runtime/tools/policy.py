from __future__ import annotations

from navi_agent.tooling import ToolContext, ToolDecision, ToolPolicy


class AllowAllToolPolicy:
    def decide(
        self,
        tool_name: str,
        arguments: dict,
        context: ToolContext | None,
    ) -> ToolDecision:
        return ToolDecision.allow()


class StaticToolPolicy:
    def __init__(self, denied_tools: dict[str, str] | None = None) -> None:
        self._denied_tools = denied_tools or {}

    def decide(
        self,
        tool_name: str,
        arguments: dict,
        context: ToolContext | None,
    ) -> ToolDecision:
        reason = self._denied_tools.get(tool_name)
        if reason:
            return ToolDecision.deny(reason)
        return ToolDecision.allow()


class SensitiveToolPolicy:
    def __init__(
        self,
        approval_required_tools: dict[str, str] | None = None,
        denied_tools: dict[str, str] | None = None,
    ) -> None:
        self._approval_required_tools = approval_required_tools or {}
        self._denied_tools = denied_tools or {}

    def decide(
        self,
        tool_name: str,
        arguments: dict,
        context: ToolContext | None,
    ) -> ToolDecision:
        denied_reason = self._denied_tools.get(tool_name)
        if denied_reason:
            return ToolDecision.deny(denied_reason)

        approval_reason = self._approval_required_tools.get(tool_name)
        if approval_reason:
            return ToolDecision.ask(
                approval_reason,
                metadata={
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )

        return ToolDecision.allow()
