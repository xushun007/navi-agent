from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from navi_agent.events import RuntimeEvent
from navi_agent.tooling import ToolArtifact, ToolContext, ToolResult


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Message:
    role: str
    content: str
    reasoning_content: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(slots=True)
class ModelResponse:
    content: str = ""
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(slots=True)
class ConversationState:
    session_id: str
    user_id: str
    messages: list[Message] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    source: str = "console"
    agent_role: str = "primary"
    parent_session_id: str | None = None
    model: str | None = None
    cwd: str | None = None


@dataclass(frozen=True, slots=True)
class SessionSearchHit:
    session_id: str
    message_id: int
    role: str
    content: str
    created_at: float
    source: str
    title: str | None = None


@dataclass(slots=True)
class RuntimeResult:
    session_id: str
    status: str
    final_response: str
    messages: list[Message] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
