from __future__ import annotations

import logging
import random
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    APIStatusError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from ..models import Message, ModelResponse, ToolCall
from .base import ModelRequest

logger = logging.getLogger("navi_agent.runtime.transport")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class OpenAICompatibleTransport:
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        client: OpenAI | Any | None = None,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 8.0,
    ) -> None:
        self._model = model
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds

    def generate(self, request: ModelRequest) -> ModelResponse:
        last_error: BaseException | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[self._serialize_message(message) for message in request.messages],
                    tools=[self._serialize_tool(tool) for tool in request.tools] or None,
                )
                return self._to_model_response(response)
            except BaseException as exc:
                last_error = exc
                if attempt > self._max_retries or not _is_retryable_error(exc):
                    raise
                delay = _retry_delay(
                    attempt=attempt,
                    base_seconds=self._base_backoff_seconds,
                    max_seconds=self._max_backoff_seconds,
                )
                logger.warning(
                    "OpenAI transport retryable error: attempt=%s delay=%.3fs error=%s",
                    attempt,
                    delay,
                    exc,
                )
                time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI transport failed without raising an exception")

    def _to_model_response(self, response: Any) -> ModelResponse:
        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
        reasoning_content = getattr(message, "reasoning_content", None)
        tool_calls = [
            ToolCall(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments=self._parse_tool_arguments(tool_call.function.arguments),
            )
            for tool_call in message.tool_calls or []
        ]
        return ModelResponse(
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _serialize_message(message: Message) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.reasoning_content:
            payload["reasoning_content"] = message.reasoning_content
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": OpenAICompatibleTransport._dump_tool_arguments(
                            tool_call.arguments
                        ),
                    },
                }
                for tool_call in message.tool_calls
            ]
        return payload

    @staticmethod
    def _serialize_tool(tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters")
                or {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            },
        }

    @staticmethod
    def _dump_tool_arguments(arguments: dict[str, Any]) -> str:
        import json

        return json.dumps(arguments)

    @staticmethod
    def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
        import json

        if not arguments:
            return {}
        return dict(json.loads(arguments))


def _retry_delay(*, attempt: int, base_seconds: float, max_seconds: float) -> float:
    delay = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    jitter = delay * 0.1 * random.random()
    return delay + jitter


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)):
        return True
    if isinstance(exc, APIStatusError):
        return getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES
    if isinstance(exc, APIError):
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return True
        if "connection" in message and any(token in message for token in ("reset", "refused", "aborted")):
            return True
    return False
