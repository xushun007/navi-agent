from __future__ import annotations

from enum import StrEnum
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
    tool_name: str | None = None
    provider: str | None = None
    model: str | None = None
    token_count: int | None = None
    finish_reason: str | None = None


@dataclass(slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None


@dataclass(slots=True)
class ModelResponse:
    content: str = ""
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: ModelUsage = field(default_factory=ModelUsage)


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
class SessionSummary:
    session_id: str
    updated_at: float
    message_count: int


@dataclass(slots=True)
class RuntimeRunRecord:
    run_id: str
    session_id: str
    user_id: str
    source: str
    agent_role: str
    status: str
    started_at: float
    updated_at: float
    completed_at: float | None = None
    start_message_id: int | None = None
    end_message_id: int | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float | None = None
    trajectory_complete: bool = True
    failure_reason: str | None = None
    completion_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ContextCompactionCheckpoint:
    session_id: str
    covered_message_count: int
    protected_head_count: int
    source_hash: str
    summary: str
    model: str | None = None
    covered_until_message_id: int | None = None
    created_at: float | None = None


@dataclass(frozen=True, slots=True)
class SessionRecallMessage:
    id: int
    role: str
    content: str
    created_at: float
    anchor: bool = False


@dataclass(frozen=True, slots=True)
class SessionRecallResult:
    session_id: str
    lineage_id: str
    title: str
    source: str
    model: str | None
    timestamp: float
    matched_message: SessionRecallMessage
    highlighted_snippet: str
    beginning: list[SessionRecallMessage]
    window: list[SessionRecallMessage]
    ending: list[SessionRecallMessage]
    messages_before: int
    messages_after: int


@dataclass(frozen=True, slots=True)
class SessionRecallView:
    session_id: str
    title: str
    source: str
    model: str | None
    timestamp: float
    messages: list[SessionRecallMessage]
    total_message_count: int
    messages_before: int
    messages_after: int
    truncated: bool


@dataclass(slots=True)
class RuntimeResult:
    session_id: str
    status: str
    final_response: str
    run_id: str = ""
    messages: list[Message] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    trajectory_complete: bool = True
    trajectory_error: str | None = None


class RuntimeMode(StrEnum):
    ONLINE = "online"
    EVAL = "eval"
    REPLAY = "replay"
    REVIEW = "review"
    SCHEDULED = "scheduled"
