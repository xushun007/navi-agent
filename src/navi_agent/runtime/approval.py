from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from navi_agent.tooling import ToolContext


@dataclass(slots=True)
class ApprovalRequest:
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    context: ToolContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ApprovalDecision:
    approved: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(
        cls,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDecision:
        return cls(
            approved=True,
            reason=reason,
            metadata=metadata or {},
        )

    @classmethod
    def deny(
        cls,
        reason: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDecision:
        return cls(
            approved=False,
            reason=reason,
            metadata=metadata or {},
        )


class ApprovalProvider(Protocol):
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision: ...


class DenyAllApprovalProvider:
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.deny(
            request.reason or f"Approval required for tool: {request.tool_name}",
            metadata={"tool_name": request.tool_name, "arguments": request.arguments},
        )


class AutoApproveApprovalProvider:
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.allow(
            reason=request.reason,
            metadata={"tool_name": request.tool_name, "arguments": request.arguments},
        )
