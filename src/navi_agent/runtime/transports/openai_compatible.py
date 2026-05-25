from __future__ import annotations

from typing import Any

from openai import OpenAI

from ..models import Message, ModelResponse, ToolCall
from .base import ModelRequest


class OpenAICompatibleTransport:
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        client: OpenAI | Any | None = None,
    ) -> None:
        self._model = model
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, request: ModelRequest) -> ModelResponse:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[self._serialize_message(message) for message in request.messages],
            tools=[self._serialize_tool(tool) for tool in request.tools] or None,
        )

        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
        tool_calls = []

        for tool_call in message.tool_calls or []:
            tool_calls.append(
                ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=self._parse_tool_arguments(tool_call.function.arguments),
                )
            )

        return ModelResponse(content=content, tool_calls=tool_calls)

    @staticmethod
    def _serialize_message(message: Message) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
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
    def _serialize_tool(tool: dict[str, str]) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": {
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
