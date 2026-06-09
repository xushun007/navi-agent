from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelCallTrace:
    iteration: int
    response_content: str
    tool_call_names: list[str] = field(default_factory=list)
    reasoning_content: str | None = None


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


@dataclass(slots=True)
class RuntimeTrace:
    session_id: str
    user_id: str
    user_message: str
    final_response: str
    status: str
    system_prompt: str | None = None
    tool_names: list[str] = field(default_factory=list)
    model_calls: list[ModelCallTrace] = field(default_factory=list)
    tool_executions: list[ToolExecutionTrace] = field(default_factory=list)
    total_iterations: int = 0
    approval_count: int = 0
    error_count: int = 0
