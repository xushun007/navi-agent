from __future__ import annotations

from navi_agent.bash_command import assess_bash_command
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


class BashCommandPolicy:
    def __init__(self, fallback: ToolPolicy | None = None) -> None:
        self._fallback = fallback or SensitiveToolPolicy()

    def decide(
        self,
        tool_name: str,
        arguments: dict,
        context: ToolContext | None,
    ) -> ToolDecision:
        if tool_name != "bash":
            return self._fallback.decide(tool_name, arguments, context)

        assessment = assess_bash_command(
            str(arguments.get("command") or ""),
            background=arguments.get("background") is True,
        )
        metadata = {
            "tool_name": tool_name,
            "arguments": arguments,
            "risk_action": assessment.action,
        }
        if assessment.action == "allow":
            return ToolDecision.allow()
        if assessment.action == "deny":
            return ToolDecision.deny(assessment.reason, metadata=metadata)
        return ToolDecision.ask(assessment.reason, metadata=metadata)
