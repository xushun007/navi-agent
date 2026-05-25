from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import Message, ModelResponse


@dataclass(slots=True)
class ModelRequest:
    messages: list[Message]
    tools: list[dict[str, str]] = field(default_factory=list)


class ModelTransport(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...
