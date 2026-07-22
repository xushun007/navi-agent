from __future__ import annotations

import logging
import time
from typing import Any

from openai import (
    APIError,
    APIStatusError,
    OpenAI,
)

from navi_agent.errors import RETRYABLE_HTTP_STATUSES, is_retryable_exception, retry_delay

from ..models import Message, ModelResponse, ModelUsage, ToolCall
from .base import ModelRequest

logger = logging.getLogger("navi_agent.runtime.transport")


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
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[self._serialize_message(message) for message in request.messages],
                    tools=[self._serialize_tool(tool) for tool in request.tools] or None,
                )
                return self._to_model_response(response)
            except Exception as exc:
                last_error = exc
                if attempt > self._max_retries or not _is_retryable_error(exc):
                    raise
                delay = retry_delay(
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
            provider="openai-compatible",
            model=str(getattr(response, "model", None) or self._model),
            usage=self._parse_usage(getattr(response, "usage", None)),
        )

    @staticmethod
    def _parse_usage(usage: Any) -> ModelUsage:
        if usage is None:
            return ModelUsage()
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        completion_details = getattr(usage, "completion_tokens_details", None)
        cost = getattr(usage, "cost", None)
        return ModelUsage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cache_read_tokens=int(getattr(prompt_details, "cached_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            reasoning_tokens=int(getattr(completion_details, "reasoning_tokens", 0) or 0),
            cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
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
    return retry_delay(
        attempt=attempt,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
    )


def _is_retryable_error(exc: Exception) -> bool:
    if is_retryable_exception(exc):
        return True
    if isinstance(exc, APIStatusError):
        return getattr(exc, "status_code", None) in RETRYABLE_HTTP_STATUSES
    if isinstance(exc, APIError):
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return True
        if "connection" in message and any(token in message for token in ("reset", "refused", "aborted")):
            return True
    return False
