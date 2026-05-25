from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


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
class ToolResult:
    tool_call_id: str
    name: str
    content: str


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
