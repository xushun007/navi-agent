from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from typing import Protocol


@dataclass(slots=True)
class ToolContext:
    session_id: str
    user_id: str
    iteration: int
    emit_output: Callable[[dict[str, Any]], None] | None = None
    cancellation_requested: Callable[[], bool] | None = None


@dataclass(slots=True)
class ToolArtifact:
    kind: str
    uri: str
    title: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    status: str = "success"
    structured_content: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ToolArtifact] = field(default_factory=list)

    @classmethod
    def ok(
        cls,
        name: str,
        content: str,
        *,
        structured_content: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        artifacts: list[ToolArtifact] | None = None,
    ) -> ToolResult:
        return cls(
            tool_call_id="",
            name=name,
            content=content,
            status="success",
            structured_content=structured_content or {},
            metadata=metadata or {},
            artifacts=artifacts or [],
        )

    @classmethod
    def error(
        cls,
        name: str,
        content: str,
        *,
        structured_content: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        artifacts: list[ToolArtifact] | None = None,
    ) -> ToolResult:
        return cls(
            tool_call_id="",
            name=name,
            content=content,
            status="error",
            structured_content=structured_content or {},
            metadata=metadata or {},
            artifacts=artifacts or [],
        )

    def bind(self, tool_call_id: str, name: str | None = None) -> ToolResult:
        return replace(
            self,
            tool_call_id=tool_call_id,
            name=name or self.name,
        )


@dataclass(slots=True)
class ToolDecision:
    allows_execution: bool
    requires_approval: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls) -> ToolDecision:
        return cls(allows_execution=True)

    @classmethod
    def ask(
        cls,
        reason: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ToolDecision:
        return cls(
            allows_execution=False,
            requires_approval=True,
            reason=reason,
            metadata=metadata or {},
        )

    @classmethod
    def deny(
        cls,
        reason: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ToolDecision:
        return cls(
            allows_execution=False,
            reason=reason,
            metadata=metadata or {},
        )


class ToolPolicy(Protocol):
    def decide(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolContext | None,
    ) -> ToolDecision: ...
