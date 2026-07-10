from __future__ import annotations

from datetime import datetime, timezone
import logging
from collections.abc import Sequence
import socket
from time import perf_counter

from navi_agent.tooling import ToolContext

from .context_engine import ContextEngine, LLMContextSummarizer
from .models import Message, RuntimeEvent, RuntimeResult
from .observers import RuntimeObserver
from .prompt_builder import PromptBuilder
from .session import InMemorySessionStore
from .store import SessionStore
from .tool_result_renderer import DefaultToolResultRenderer, ToolResultRenderer
from .tools import ToolRegistry
from .transports import ModelRequest, ModelTransport
from navi_agent.telemetry import ModelCallTrace, ToolExecutionTrace, TraceStore, RuntimeTrace

logger = logging.getLogger("navi_agent.runtime")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _duration_ms(started_perf: float) -> int:
    return int((perf_counter() - started_perf) * 1000)


def _pop_trace_timing(metadata: dict[str, object]) -> tuple[dict[str, object], str | None, str | None, int]:
    started_at = metadata.pop("_trace_started_at", None)
    completed_at = metadata.pop("_trace_completed_at", None)
    duration_ms = metadata.pop("_trace_duration_ms", 0)
    if not isinstance(started_at, str):
        started_at = None
    if not isinstance(completed_at, str):
        completed_at = None
    if not isinstance(duration_ms, int):
        duration_ms = 0
    return metadata, started_at, completed_at, duration_ms


def _classify_error(exc: Exception) -> dict[str, object]:
    http_status = getattr(exc, "status_code", None)
    retryable = False
    error_category = "fatal"
    if isinstance(http_status, int) and http_status in {429, 500, 502, 503, 504}:
        retryable = True
        error_category = "retryable"
    else:
        text = str(exc).lower()
        if isinstance(exc, (TimeoutError, socket.timeout, ConnectionError, OSError)) or "timeout" in text or "timed out" in text:
            retryable = True
            error_category = "retryable"
    return {
        "error_category": error_category,
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
        "retryable": retryable,
        "http_status": http_status if isinstance(http_status, int) else None,
    }


def _classify_tool_error(
    *,
    tool_result,
    tool_metadata: dict[str, object],
) -> dict[str, object]:
    if tool_result.status != "error":
        return {
            "error_category": None,
            "error_type": None,
            "error_message": None,
            "retryable": None,
            "http_status": None,
        }
    error_type = tool_metadata.get("error_type")
    error_message = tool_metadata.get("error_message")
    http_status = tool_metadata.get("http_status")
    retryable = tool_metadata.get("retryable")
    error_category = tool_metadata.get("error_category")

    if isinstance(tool_result.structured_content.get("approval_required"), bool) and tool_result.structured_content.get("approval_required"):
        return {
            "error_category": "blocked",
            "error_type": error_type if isinstance(error_type, str) else "ApprovalDenied",
            "error_message": error_message if isinstance(error_message, str) else tool_result.content,
            "retryable": False,
            "http_status": http_status if isinstance(http_status, int) else None,
        }

    structured_timeout = tool_result.structured_content.get("timed_out") is True
    content = tool_result.content.lower()
    timeout_text = "timed out" in content or "timeout" in content
    if structured_timeout or timeout_text:
        return {
            "error_category": "retryable",
            "error_type": error_type if isinstance(error_type, str) else "TimeoutError",
            "error_message": error_message if isinstance(error_message, str) else tool_result.content,
            "retryable": True,
            "http_status": http_status if isinstance(http_status, int) else None,
        }

    if isinstance(error_category, str):
        return {
            "error_category": error_category,
            "error_type": error_type if isinstance(error_type, str) else None,
            "error_message": error_message if isinstance(error_message, str) else tool_result.content,
            "retryable": retryable if isinstance(retryable, bool) else None,
            "http_status": http_status if isinstance(http_status, int) else None,
        }

    return {
        "error_category": "fatal",
        "error_type": error_type if isinstance(error_type, str) else None,
        "error_message": error_message if isinstance(error_message, str) else tool_result.content,
        "retryable": retryable if isinstance(retryable, bool) else False,
        "http_status": http_status if isinstance(http_status, int) else None,
    }


class AgentRuntime:
    def __init__(
        self,
        transport: ModelTransport,
        tool_registry: ToolRegistry | None = None,
        session_store: SessionStore | None = None,
        prompt_builder: PromptBuilder | None = None,
        trace_store: TraceStore | None = None,
        observers: Sequence[RuntimeObserver] | None = None,
        tool_result_renderer: ToolResultRenderer | None = None,
        context_engine: ContextEngine | None = None,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
        max_iterations: int = 8,
    ) -> None:
        self._transport = transport
        self._tool_registry = tool_registry or ToolRegistry()
        self._session_store = session_store or InMemorySessionStore()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._trace_store = trace_store
        self._observers = list(observers or [])
        self._tool_result_renderer = tool_result_renderer or DefaultToolResultRenderer()
        self._context_engine = context_engine or ContextEngine(summarizer=LLMContextSummarizer(transport))
        self._enabled_toolsets = enabled_toolsets
        self._disabled_toolsets = disabled_toolsets
        self._max_iterations = max_iterations

    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> RuntimeResult:
        run_started_at = _utc_now_iso()
        run_started_perf = perf_counter()
        logger.info("Starting runtime conversation: session_id=%s user_id=%s", session_id, user_id)
        self._emit_event(
            RuntimeEvent(
                name="runtime.started",
                session_id=session_id,
                user_id=user_id,
            )
        )
        session = self._session_store.load(session_id=session_id, user_id=user_id)
        for message in self._prompt_builder.build_initial_messages(
            session=session,
            user_message=user_message,
            system_prompt=system_prompt,
        ):
            self._session_store.append(session, message)
        injected_skill_names = self._prompt_builder.last_injected_skill_names
        tool_results = []
        model_calls: list[ModelCallTrace] = []
        tool_executions: list[ToolExecutionTrace] = []

        for iteration in range(self._max_iterations):
            iteration_number = iteration + 1
            logger.debug(
                "Running iteration: session_id=%s iteration=%s",
                session_id,
                iteration_number,
            )
            self._emit_event(
                RuntimeEvent(
                    name="iteration.started",
                    session_id=session_id,
                    user_id=user_id,
                    iteration=iteration_number,
                )
            )
            model_started_at = _utc_now_iso()
            model_started_perf = perf_counter()
            context_result = self._context_engine.build(self._session_store.snapshot(session))
            if context_result.compressed:
                logger.info(
                    "Runtime context compressed: session_id=%s original_messages=%s compressed_messages=%s final_messages=%s tokens=%s->%s threshold=%s",
                    session_id,
                    context_result.original_message_count,
                    context_result.compressed_message_count,
                    len(context_result.messages),
                    context_result.estimated_tokens_before,
                    context_result.estimated_tokens_after,
                    context_result.threshold_tokens,
                )
                self._emit_event(
                    RuntimeEvent(
                        name="context.compressed",
                        session_id=session_id,
                        user_id=user_id,
                        iteration=iteration_number,
                        metadata={
                            "original_message_count": context_result.original_message_count,
                            "compressed_message_count": context_result.compressed_message_count,
                            "final_message_count": len(context_result.messages),
                            "estimated_tokens_before": context_result.estimated_tokens_before,
                            "estimated_tokens_after": context_result.estimated_tokens_after,
                            "threshold_tokens": context_result.threshold_tokens,
                            "protected_head_count": context_result.protected_head_count,
                            "protected_tail_count": context_result.protected_tail_count,
                            "latest_user_anchored": context_result.latest_user_anchored,
                            "summary_status": context_result.summary_status,
                        },
                    )
                )
            try:
                response = self._transport.generate(
                    ModelRequest(
                        messages=context_result.messages,
                        tools=self._tool_registry.schemas(
                            enabled_toolsets=self._enabled_toolsets,
                            disabled_toolsets=self._disabled_toolsets,
                        ),
                    )
                )
            except Exception as exc:
                error_info = _classify_error(exc)
                logger.exception("Model transport failed: session_id=%s error=%s", session_id, exc)
                result = RuntimeResult(
                    session_id=session.session_id,
                    status="failed",
                    final_response="",
                    messages=self._session_store.snapshot(session),
                    tool_results=tool_results,
                )
                self._record_trace(
                    session_id=session.session_id,
                    user_id=user_id,
                    user_message=user_message,
                    system_prompt=system_prompt,
                    injected_skill_names=injected_skill_names,
                    result=result,
                    model_calls=model_calls,
                    tool_executions=tool_executions,
                    started_at=run_started_at,
                    duration_ms=_duration_ms(run_started_perf),
                    error_info=error_info,
                    attempt_count=iteration_number,
                )
                self._emit_event(
                    RuntimeEvent(
                        name="runtime.completed",
                        session_id=session.session_id,
                        user_id=user_id,
                        iteration=iteration_number,
                        metadata={"status": result.status, **error_info},
                    )
                )
                return result
            self._emit_event(
                RuntimeEvent(
                    name="model.responded",
                    session_id=session_id,
                    user_id=user_id,
                    iteration=iteration_number,
                    metadata={"tool_call_count": len(response.tool_calls)},
                )
            )
            model_calls.append(
                ModelCallTrace(
                    iteration=iteration_number,
                    response_content=response.content,
                    tool_call_names=[tool_call.name for tool_call in response.tool_calls],
                    reasoning_content=response.reasoning_content,
                    started_at=model_started_at,
                    completed_at=_utc_now_iso(),
                    duration_ms=_duration_ms(model_started_perf),
                )
            )

            assistant_message = Message(
                role="assistant",
                content=response.content,
                reasoning_content=response.reasoning_content,
                tool_calls=response.tool_calls,
            )
            self._session_store.append(session, assistant_message)

            if not response.tool_calls:
                logger.info(
                    "Runtime conversation completed: session_id=%s status=success",
                    session_id,
                )
                result = RuntimeResult(
                    session_id=session.session_id,
                    status="success",
                    final_response=response.content,
                    messages=self._session_store.snapshot(session),
                    tool_results=tool_results,
                )
                self._record_trace(
                    session_id=session.session_id,
                    user_id=user_id,
                    user_message=user_message,
                    system_prompt=system_prompt,
                    injected_skill_names=injected_skill_names,
                    result=result,
                    model_calls=model_calls,
                    tool_executions=tool_executions,
                    started_at=run_started_at,
                    duration_ms=_duration_ms(run_started_perf),
                )
                self._emit_event(
                    RuntimeEvent(
                        name="runtime.completed",
                        session_id=session.session_id,
                        user_id=user_id,
                        iteration=iteration_number,
                        metadata={"status": result.status},
                    )
                )
                return result

            tool_context = ToolContext(
                session_id=session.session_id,
                user_id=user_id,
                iteration=iteration_number,
            )
            for tool_result in self._tool_registry.dispatch(
                response.tool_calls,
                context=tool_context,
                enabled_toolsets=self._enabled_toolsets,
                disabled_toolsets=self._disabled_toolsets,
            ):
                tool_metadata, tool_started_at, tool_completed_at, tool_duration_ms = _pop_trace_timing(
                    dict(tool_result.metadata)
                )
                logger.debug(
                    "Tool executed: session_id=%s tool=%s",
                    session_id,
                    tool_result.name,
                )
                tool_results.append(tool_result)
                tool_executions.append(
                    ToolExecutionTrace(
                        iteration=iteration_number,
                        tool_call_id=tool_result.tool_call_id,
                        tool_name=tool_result.name,
                        status=tool_result.status,
                        arguments=next(
                            (
                                tool_call.arguments
                                for tool_call in response.tool_calls
                                if tool_call.id == tool_result.tool_call_id
                            ),
                            {},
                        ),
                        content=tool_result.content,
                        metadata=tool_metadata,
                        structured_content=dict(tool_result.structured_content),
                        approval_required=bool(
                            tool_result.structured_content.get("approval_required")
                        ),
                        **_classify_tool_error(tool_result=tool_result, tool_metadata=tool_metadata),
                        started_at=tool_started_at,
                        completed_at=tool_completed_at,
                        duration_ms=tool_duration_ms,
                    )
                )
                self._emit_event(
                    RuntimeEvent(
                        name="tool.executed",
                        session_id=session_id,
                        user_id=user_id,
                        iteration=iteration_number,
                        metadata={
                            "tool_name": tool_result.name,
                            "status": tool_result.status,
                        },
                    )
                )
                self._session_store.append(
                    session,
                    Message(
                        role="tool",
                        content=self._render_tool_message(tool_result),
                        tool_call_id=tool_result.tool_call_id,
                    ),
                )

        logger.error("Runtime iteration limit exceeded: session_id=%s", session_id)
        result = RuntimeResult(
            session_id=session.session_id,
            status="iteration_limit_exceeded",
            final_response="",
            messages=self._session_store.snapshot(session),
            tool_results=tool_results,
        )
        self._record_trace(
            session_id=session.session_id,
            user_id=user_id,
            user_message=user_message,
            system_prompt=system_prompt,
            injected_skill_names=injected_skill_names,
            result=result,
            model_calls=model_calls,
            tool_executions=tool_executions,
            started_at=run_started_at,
            duration_ms=_duration_ms(run_started_perf),
        )
        self._emit_event(
            RuntimeEvent(
                name="runtime.completed",
                session_id=session.session_id,
                user_id=user_id,
                iteration=self._max_iterations,
                metadata={"status": result.status},
            )
        )
        return result

    def _record_trace(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None,
        injected_skill_names: list[str],
        result: RuntimeResult,
        model_calls: list[ModelCallTrace],
        tool_executions: list[ToolExecutionTrace],
        started_at: str,
        duration_ms: int,
        error_info: dict[str, object] | None = None,
        attempt_count: int = 0,
    ) -> None:
        if self._trace_store is None:
            return
        error_info = error_info or {}
        self._trace_store.record(
            RuntimeTrace(
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                final_response=result.final_response,
                status=result.status,
                system_prompt=system_prompt,
                injected_skill_names=list(injected_skill_names),
                tool_names=[item.name for item in result.tool_results],
                model_calls=list(model_calls),
                tool_executions=list(tool_executions),
                total_iterations=len(model_calls),
                approval_count=sum(1 for item in tool_executions if item.approval_required),
                error_count=sum(1 for item in tool_executions if item.status == "error"),
                error_category=error_info.get("error_category") if isinstance(error_info.get("error_category"), str) else None,
                error_type=error_info.get("error_type") if isinstance(error_info.get("error_type"), str) else None,
                error_message=error_info.get("error_message") if isinstance(error_info.get("error_message"), str) else None,
                retryable=error_info.get("retryable") if isinstance(error_info.get("retryable"), bool) else None,
                http_status=error_info.get("http_status") if isinstance(error_info.get("http_status"), int) else None,
                attempt_count=attempt_count,
                started_at=started_at,
                completed_at=_utc_now_iso(),
                duration_ms=duration_ms,
            )
        )

    def _emit_event(self, event: RuntimeEvent) -> None:
        for observer in self._observers:
            observer.on_event(event)

    def _render_tool_message(self, tool_result) -> str:
        rendered = self._tool_result_renderer.render(tool_result).strip()
        if rendered:
            return rendered
        return f"{tool_result.name}: {tool_result.status}"

    def get_latest_trace(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> RuntimeTrace | None:
        if self._trace_store is None:
            return None
        return self._trace_store.get_latest_trace(
            session_id=session_id,
            user_id=user_id,
        )

    def get_session_traces(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
    ) -> list[RuntimeTrace]:
        if self._trace_store is None:
            return []
        return self._trace_store.get_session_traces(
            session_id=session_id,
            user_id=user_id,
        )
