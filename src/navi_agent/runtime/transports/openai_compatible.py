from __future__ import annotations

import logging
import time
from typing import Any, Callable

from openai import (
    APIError,
    APIStatusError,
    OpenAI,
)

from navi_agent.errors import RETRYABLE_HTTP_STATUSES, is_retryable_exception, retry_delay

from ..models import Message, ModelResponse, ModelUsage, ToolCall
from ..agent.control import RunCancelledError
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
            self._raise_if_cancelled(request)
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[self._serialize_message(message) for message in request.messages],
                    tools=[self._serialize_tool(tool) for tool in request.tools] or None,
                )
                self._raise_if_cancelled(request)
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

    def generate_stream(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
    ) -> ModelResponse:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 2):
            self._raise_if_cancelled(request)
            stream_started = False
            stream = None
            try:
                stream = self._client.chat.completions.create(
                    model=self._model,
                    messages=[self._serialize_message(message) for message in request.messages],
                    tools=[self._serialize_tool(tool) for tool in request.tools] or None,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                content_parts: list[str] = []
                reasoning_parts: list[str] = []
                tool_call_parts: dict[int, dict[str, str]] = {}
                model = self._model
                usage = ModelUsage()

                for chunk in stream:
                    self._raise_if_cancelled(request)
                    stream_started = True
                    model = str(getattr(chunk, "model", None) or model)
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage = self._parse_usage(chunk_usage)
                    choices = getattr(chunk, "choices", None) or []
                    for choice in choices:
                        delta = getattr(choice, "delta", None)
                        if delta is None:
                            continue
                        content = getattr(delta, "content", None)
                        if isinstance(content, str) and content:
                            content_parts.append(content)
                            on_text_delta(content)
                        reasoning = getattr(delta, "reasoning_content", None)
                        if isinstance(reasoning, str) and reasoning:
                            reasoning_parts.append(reasoning)
                        for tool_call in getattr(delta, "tool_calls", None) or []:
                            index = int(getattr(tool_call, "index", 0) or 0)
                            parts = tool_call_parts.setdefault(
                                index,
                                {"id": "", "name": "", "arguments": ""},
                            )
                            call_id = getattr(tool_call, "id", None)
                            if isinstance(call_id, str):
                                parts["id"] += call_id
                            function = getattr(tool_call, "function", None)
                            if function is None:
                                continue
                            name = getattr(function, "name", None)
                            if isinstance(name, str):
                                parts["name"] += name
                            arguments = getattr(function, "arguments", None)
                            if isinstance(arguments, str):
                                parts["arguments"] += arguments

                return ModelResponse(
                    content="".join(content_parts),
                    reasoning_content="".join(reasoning_parts) or None,
                    tool_calls=[
                        ToolCall(
                            id=parts["id"],
                            name=parts["name"],
                            arguments=self._parse_tool_arguments(parts["arguments"]),
                        )
                        for _, parts in sorted(tool_call_parts.items())
                    ],
                    provider="openai-compatible",
                    model=model,
                    usage=usage,
                )
            except RunCancelledError:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
                raise
            except Exception as exc:
                last_error = exc
                if stream_started or attempt > self._max_retries or not _is_retryable_error(exc):
                    raise
                delay = retry_delay(
                    attempt=attempt,
                    base_seconds=self._base_backoff_seconds,
                    max_seconds=self._max_backoff_seconds,
                )
                logger.warning(
                    "OpenAI streaming transport retryable error: attempt=%s delay=%.3fs error=%s",
                    attempt,
                    delay,
                    exc,
                )
                time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI streaming transport failed without raising an exception")

    @staticmethod
    def _raise_if_cancelled(request: ModelRequest) -> None:
        if request.cancellation_requested is not None and request.cancellation_requested():
            raise RunCancelledError("model request cancelled")

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
