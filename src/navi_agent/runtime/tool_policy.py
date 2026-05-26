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
