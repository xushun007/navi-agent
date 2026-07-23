from __future__ import annotations

from collections.abc import Callable
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


class WorkspaceYoloApprovalProvider:
    _WORKSPACE_TOOLS = {"bash", "code_executor", "write_file", "patch"}

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        if request.tool_name in self._WORKSPACE_TOOLS:
            return ApprovalDecision.allow(
                reason=f"YOLO workspace approval for tool: {request.tool_name}",
                metadata={
                    "tool_name": request.tool_name,
                    "arguments": request.arguments,
                    "yolo": True,
                },
            )
        return ApprovalDecision.deny(
            request.reason or f"Approval required for non-workspace tool: {request.tool_name}",
            metadata={
                "tool_name": request.tool_name,
                "arguments": request.arguments,
                "yolo": True,
            },
        )


class CliApprovalProvider:
    def __init__(
        self,
        input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._input_fn = input_fn or input
        self._output_fn = output_fn or print

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self._output_fn("")
        self._output_fn("Tool approval required")
        self._output_fn(f"tool: {request.tool_name}")
        self._output_fn(f"reason: {request.reason}")
        self._output_fn(f"arguments: {request.arguments}")
        answer = self._input_fn("Allow? [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            return ApprovalDecision.allow(
                reason=f"Approved in CLI for tool: {request.tool_name}",
                metadata={"tool_name": request.tool_name, "arguments": request.arguments},
            )
        return ApprovalDecision.deny(
            reason=f"Approval denied in CLI for tool: {request.tool_name}",
            metadata={"tool_name": request.tool_name, "arguments": request.arguments},
        )
