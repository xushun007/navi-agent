from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class ModelCallTrace:
    iteration: int
    response_content: str
    tool_call_names: list[str] = field(default_factory=list)
    reasoning_content: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int = 0


@dataclass(slots=True)
class ToolExecutionTrace:
    iteration: int
    tool_call_id: str
    tool_name: str
    status: str
    arguments: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    structured_content: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = False
    error_category: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    retryable: bool | None = None
    http_status: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int = 0


@dataclass(slots=True)
class RuntimeTrace:
    session_id: str
    user_id: str
    user_message: str
    final_response: str
    status: str
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    system_prompt: str | None = None
    injected_skill_names: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    model_calls: list[ModelCallTrace] = field(default_factory=list)
    tool_executions: list[ToolExecutionTrace] = field(default_factory=list)
    total_iterations: int = 0
    approval_count: int = 0
    error_count: int = 0
    error_category: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    retryable: bool | None = None
    http_status: int | None = None
    attempt_count: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int = 0
