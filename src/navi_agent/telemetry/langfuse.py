from __future__ import annotations

from typing import Any, Protocol

from navi_agent.config import LangfuseSettings

from .models import RuntimeTrace


def is_langfuse_sdk_available() -> bool:
    try:
        from langfuse import Langfuse  # noqa: F401
    except ImportError:
        return False
    return True


class LangfuseTraceClient(Protocol):
    def generation(self, **kwargs: Any) -> None: ...
    def span(self, **kwargs: Any) -> None: ...
    def event(self, **kwargs: Any) -> None: ...


class LangfuseClient(Protocol):
    def trace(self, **kwargs: Any) -> LangfuseTraceClient: ...
    def flush(self) -> None: ...


class LangfuseTraceExporter:
    def __init__(self, client: LangfuseClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: LangfuseSettings) -> "LangfuseTraceExporter":
        if not settings.enabled:
            raise ValueError("Langfuse is not enabled")
        if not is_langfuse_sdk_available():
            raise RuntimeError(
                "Langfuse SDK is not installed. Add the 'langfuse' package to enable exporting."
            )
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            raise RuntimeError(
                "Langfuse SDK is not installed. Add the 'langfuse' package to enable exporting."
            ) from exc
        client = Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            host=settings.host,
        )
        return cls(client=client)

    def export_trace(self, trace: RuntimeTrace) -> None:
        langfuse_trace = self._client.trace(
            id=trace.trace_id,
            name="navi-agent-runtime",
            session_id=trace.session_id,
            user_id=trace.user_id,
            input=trace.user_message,
            output=trace.final_response,
            metadata={
                "trace_id": trace.trace_id,
                "status": trace.status,
                "system_prompt": trace.system_prompt,
                "tool_names": list(trace.tool_names),
                "total_iterations": trace.total_iterations,
                "approval_count": trace.approval_count,
                "error_count": trace.error_count,
                "started_at": trace.started_at,
                "completed_at": trace.completed_at,
                "duration_ms": trace.duration_ms,
            },
        )
        for model_call in trace.model_calls:
            langfuse_trace.generation(
                name=f"model.iteration.{model_call.iteration}",
                input={"tool_call_names": list(model_call.tool_call_names)},
                output=model_call.response_content,
                metadata={
                    "iteration": model_call.iteration,
                    "reasoning_content": model_call.reasoning_content,
                    "started_at": model_call.started_at,
                    "completed_at": model_call.completed_at,
                    "duration_ms": model_call.duration_ms,
                },
            )
        for tool_execution in trace.tool_executions:
            langfuse_trace.span(
                name=f"tool.{tool_execution.tool_name}",
                input=tool_execution.arguments,
                output=tool_execution.content,
                metadata={
                    "iteration": tool_execution.iteration,
                    "tool_call_id": tool_execution.tool_call_id,
                    "status": tool_execution.status,
                    "approval_required": tool_execution.approval_required,
                    "structured_content": tool_execution.structured_content,
                    "metadata": tool_execution.metadata,
                    "started_at": tool_execution.started_at,
                    "completed_at": tool_execution.completed_at,
                    "duration_ms": tool_execution.duration_ms,
                },
            )
            if tool_execution.approval_required:
                langfuse_trace.event(
                    name=f"approval.{tool_execution.tool_name}",
                    metadata={
                        "iteration": tool_execution.iteration,
                        "tool_call_id": tool_execution.tool_call_id,
                        "arguments": tool_execution.arguments,
                    },
                )
        self._client.flush()
