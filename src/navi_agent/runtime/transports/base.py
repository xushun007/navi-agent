from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..models import Message, ModelResponse


@dataclass(slots=True)
class ModelRequest:
    messages: list[Message]
    tools: list[dict[str, Any]] = field(default_factory=list)


class ModelTransport(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...


class StreamingModelTransport(ModelTransport, Protocol):
    def generate_stream(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
    ) -> ModelResponse: ...
