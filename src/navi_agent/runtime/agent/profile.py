from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Resolved execution choices for one agent runtime."""

    role: str
    max_iterations: int
    enabled_toolsets: tuple[str, ...] | None = None
    disabled_toolsets: tuple[str, ...] | None = None
    allow_delegation: bool = False
    non_interactive: bool = False

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("agent role must not be empty")
        if self.max_iterations <= 0:
            raise ValueError("agent max_iterations must be positive")
