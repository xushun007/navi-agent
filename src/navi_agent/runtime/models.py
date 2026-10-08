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
    """Session message; the internal ``runtime`` role is adapted by transports."""

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
    """Long-lived session state spanning one or more execution turns."""

    session_id: str
    user_id: str
    messages: list[Message] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Run-scoped task intent and the optional evidence required to finish it."""

    objective: str
    acceptance: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.objective.strip():
            raise ValueError("task objective must not be empty")


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    source: str = "console"
    agent_role: str = "primary"
    parent_session_id: str | None = None
    model: str | None = None
    cwd: str | None = None
    environment_id: str | None = None
    task_spec: TaskSpec | None = None


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: str
    updated_at: float
    message_count: int


@dataclass(slots=True)
class RuntimeRunRecord:
    """Durable record for one execution turn within a session.

    ``run_id`` is retained as the persisted identifier for compatibility with
    existing session stores, event logs, and trace URLs. At the runtime layer,
    it is the identity of a turn: a user request (or its approval resume) and
    all of its steps.
    """

    run_id: str
    session_id: str
    user_id: str
    source: str
    agent_role: str
    status: str
    started_at: float
    updated_at: float
    environment_id: str | None = None
    task_spec: TaskSpec | None = None
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

    @property
    def turn_id(self) -> str:
        """Semantic alias for the persisted ``run_id``."""
        return self.run_id


@dataclass(frozen=True, slots=True)
class StepSnapshot:
    """Immutable projection of the inputs visible to one step in a turn."""

    step_id: str
    run_id: str
    session_id: str
    iteration: int
    model: str | None
    environment_id: str
    context_hash: str
    tool_schema_hash: str
    capability_names: tuple[str, ...]
    prompt_sources: tuple[str, ...]
    created_at: str


class OperationStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AWAITING_INPUT = "awaiting_input"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """Durable lifecycle record for one tool operation."""

    operation_id: str
    run_id: str
    session_id: str
    step_id: str
    environment_id: str
    tool_call_id: str
    capability_name: str
    arguments_hash: str
    status: OperationStatus
    created_at: float
    updated_at: float
    completed_at: float | None = None
    result_hash: str | None = None


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
    task_spec: TaskSpec | None = None
    completion_verified: bool | None = None
    completion_reason: str | None = None
    messages: list[Message] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    trajectory_complete: bool = True
    trajectory_error: str | None = None

    @property
    def turn_id(self) -> str:
        """Semantic alias for the persisted ``run_id``."""
        return self.run_id


class RuntimeMode(StrEnum):
    ONLINE = "online"
    EVAL = "eval"
    REPLAY = "replay"
    REVIEW = "review"
    SCHEDULED = "scheduled"
