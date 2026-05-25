from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RuntimeTrace:
    session_id: str
    user_id: str
    user_message: str
    final_response: str
    status: str
    tool_names: list[str] = field(default_factory=list)
