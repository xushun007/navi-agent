from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from navi_agent.runtime import (
    AgentRuntime,
    InMemorySessionStore,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    RuntimeMode,
    ToolCall,
)
from navi_agent.telemetry import InMemoryTraceStore


@dataclass(frozen=True, slots=True)
class NaviInspectResult:
    session_id: str
    run_id: str
    trace_id: str
    status: str
    completion: str
    iterations: int
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def metadata(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "status": self.status,
            "iterations": self.iterations,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


class InspectBridgeTransport:
    def generate(self, request: ModelRequest) -> ModelResponse:
        return asyncio.run(self._generate(request))

    async def _generate(self, request: ModelRequest) -> ModelResponse:
        async with AsyncOpenAI(api_key="inspect") as client:
            response = await client.chat.completions.create(
                model="inspect",
                messages=[self._serialize_message(message) for message in request.messages],
                tools=[self._serialize_tool(tool) for tool in request.tools],
            )
        return self._to_model_response(response)

    @staticmethod
    def _serialize_message(message) -> dict[str, Any]:
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
                        "arguments": json.dumps(
                            tool_call.arguments,
                            ensure_ascii=False,
                            sort_keys=True,
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
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            },
        }

    @staticmethod
    def _to_model_response(response: Any) -> ModelResponse:
        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)
        return ModelResponse(
            content=message.content or "",
            tool_calls=[
                ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=_parse_arguments(tool_call.function.arguments),
                )
                for tool_call in message.tool_calls or []
            ],
            provider="inspect",
            model=str(getattr(response, "model", None) or "inspect"),
            finish_reason=(
                str(choice.finish_reason)
                if getattr(choice, "finish_reason", None) is not None
                else None
            ),
            usage=ModelUsage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            ),
        )


def run_navi_agent(
    prompt: str,
    *,
    sample_id: str,
    transport=None,
) -> NaviInspectResult:
    session_id = f"inspect:general-qa:{sample_id}:{uuid4().hex[:8]}"
    trace_store = InMemoryTraceStore()
    runtime = AgentRuntime(
        transport=transport or InspectBridgeTransport(),
        session_store=InMemorySessionStore(),
        trace_store=trace_store,
        model="inspect",
        max_iterations=3,
    )
    result = runtime.run_conversation(
        session_id=session_id,
        user_id="inspect-general-qa",
        user_message=prompt,
        source="inspect",
        mode=RuntimeMode.EVAL,
    )
    trace = trace_store.get_latest_trace(
        session_id=session_id,
        user_id="inspect-general-qa",
    )
    if trace is None:
        raise RuntimeError(f"Navi runtime did not record a trace for {sample_id}")
    return NaviInspectResult(
        session_id=session_id,
        run_id=result.run_id,
        trace_id=trace.trace_id,
        status=result.status,
        completion=result.final_response,
        iterations=trace.total_iterations,
        duration_ms=trace.duration_ms,
        input_tokens=sum(call.input_tokens for call in trace.model_calls),
        output_tokens=sum(call.output_tokens for call in trace.model_calls),
        cost_usd=sum(call.cost_usd or 0.0 for call in trace.model_calls),
    )


def _parse_arguments(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}
