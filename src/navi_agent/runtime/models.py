from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolContext:
    session_id: str
    user_id: str
    iteration: int


@dataclass(slots=True)
class Message:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(slots=True)
class ModelResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


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
class ConversationState:
    session_id: str
    user_id: str
    messages: list[Message] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeResult:
    session_id: str
    status: str
    final_response: str
    messages: list[Message] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeEvent:
    name: str
    session_id: str
    user_id: str
    iteration: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
