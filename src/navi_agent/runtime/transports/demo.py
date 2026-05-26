from __future__ import annotations

from .base import ModelRequest
from ..models import ModelResponse


class DemoTransport:
    def generate(self, request: ModelRequest) -> ModelResponse:
        user_messages = [message.content for message in request.messages if message.role == "user"]
        latest = user_messages[-1] if user_messages else ""
        return ModelResponse(
            content=(
                "Demo mode is active.\n"
                f"Latest user message: {latest}\n"
                f"Available tools: {', '.join(tool['name'] for tool in request.tools) or 'none'}"
            )
        )
