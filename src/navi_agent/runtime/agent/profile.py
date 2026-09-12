from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .prompt_pipeline import PromptContributor
    from ..resources import ToolProvider
    from ..transports import ModelTransport


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Resolved execution choices for one agent runtime."""

    role: str
    max_iterations: int
    enabled_toolsets: tuple[str, ...] | None = None
    disabled_toolsets: tuple[str, ...] | None = None
    allow_delegation: bool = False
    non_interactive: bool = False
    transport: ModelTransport | None = None
    model: str | None = None
    context_limit_tokens: int | None = None
    prompt_contributors: tuple[PromptContributor, ...] = ()
    tool_providers: tuple[ToolProvider, ...] = ()

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("agent role must not be empty")
        if self.max_iterations <= 0:
            raise ValueError("agent max_iterations must be positive")
        if self.context_limit_tokens is not None and self.context_limit_tokens <= 0:
            raise ValueError("agent context_limit_tokens must be positive")
