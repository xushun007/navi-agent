from __future__ import annotations

from datetime import datetime, timezone
import logging
from collections.abc import Callable, Sequence
from threading import Lock
from time import perf_counter
from uuid import uuid4

from navi_agent.errors import classify_exception
from navi_agent.tooling import ToolContext

from .background_tasks import BackgroundTask, BackgroundTaskManager
from .context_engine import ContextBuildResult, ContextEngine, LLMContextSummarizer
from .models import Message, RuntimeResult, SessionMetadata
from .prompt_builder import PromptBuilder
from .run_control import RunCancellationToken
from .session import InMemorySessionStore
from .store import SessionStore
from .tool_result_renderer import DefaultToolResultRenderer, ToolResultRenderer
from .tools import ToolRegistry
from .transports import ModelRequest, ModelTransport
from navi_agent.telemetry import (
    ModelCallTrace,
    RuntimeEventStore,
    RuntimeTrace,
    ToolExecutionTrace,
    TraceStore,
)
from navi_agent.events import EventStoreWriter, RuntimeEvent, RuntimeEventPublisher, RuntimeEventSubscriber

logger = logging.getLogger("navi_agent.runtime")

_ITERATION_LIMIT_RESPONSE = "任务未能在当前执行次数内完成。请缩小任务范围或补充更明确的信息后重试。"
_CANCELLED_RESPONSE = "当前任务已停止。"


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


def _model_failure_response(error_info: dict[str, object]) -> str:
    retryable = error_info.get("retryable") is True
    http_status = error_info.get("http_status")
    error_type = error_info.get("error_type")
    prefix = "模型服务暂时不可用" if retryable else "模型服务调用失败"
    details = []
    if isinstance(http_status, int):
        details.append(f"HTTP {http_status}")
    if isinstance(error_type, str) and error_type:
        details.append(error_type)
    if details:
        prefix = f"{prefix}（{', '.join(details)}）"
    if retryable:
        return f"{prefix}。请稍后重试；如果持续出现，检查模型服务或网络状态。"
    return f"{prefix}。请检查模型配置、请求参数或服务状态。"


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
        event_subscribers: Sequence[RuntimeEventSubscriber] | None = None,
        tool_result_renderer: ToolResultRenderer | None = None,
        context_engine: ContextEngine | None = None,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
        event_store: RuntimeEventStore | None = None,
        background_task_manager: BackgroundTaskManager | None = None,
        max_iterations: int = 8,
        agent_role: str = "primary",
        parent_session_id: str | None = None,
        model: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self._transport = transport
        self._tool_registry = tool_registry or ToolRegistry()
        self._session_store = session_store or InMemorySessionStore()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._trace_store = trace_store
        self._event_publisher = RuntimeEventPublisher(event_subscribers or ())
        self._tool_result_renderer = tool_result_renderer or DefaultToolResultRenderer()
        self._context_engine = context_engine or ContextEngine(summarizer=LLMContextSummarizer(transport))
        self._enabled_toolsets = enabled_toolsets
        self._disabled_toolsets = disabled_toolsets
        if event_store is not None:
            self._event_publisher.subscribe(EventStoreWriter(event_store))
        self._background_task_manager = background_task_manager
        self._max_iterations = max_iterations
        self._agent_role = agent_role
        self._parent_session_id = parent_session_id
        self._model = model
        self._cwd = cwd

    def add_background_task_listener(self, listener: Callable[[BackgroundTask], None]) -> bool:
        if self._background_task_manager is None:
            return False
        self._background_task_manager.add_completion_listener(listener)
        return True

    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
        source: str = "console",
        event_subscribers: Sequence[RuntimeEventSubscriber] | None = None,
        cancellation_token: RunCancellationToken | None = None,
    ) -> RuntimeResult:
        cancellation_token = cancellation_token or RunCancellationToken()
        run_started_at = _utc_now_iso()
        run_started_perf = perf_counter()
        run_id = uuid4().hex
        event_sequence = 0
        event_publish_lock = Lock()
        request_publisher = RuntimeEventPublisher(event_subscribers or ())

        def publish_event(
            *,
            kind: str,
            source: str,
            name: str,
            iteration: int | None = None,
            item_id: str | None = None,
            payload: dict[str, object] | None = None,
        ) -> None:
            nonlocal event_sequence
            with event_publish_lock:
                event_sequence += 1
                event = RuntimeEvent(
                    session_id=session_id,
                    user_id=user_id,
                    run_id=run_id,
                    sequence=event_sequence,
                    kind=kind,
                    source=source,
                    name=name,
                    iteration=iteration,
                    item_id=item_id,
                    metadata=dict(payload or {}),
                )
                self._event_publisher.publish(event)
                request_publisher.publish(event)

        logger.info("Starting runtime conversation: session_id=%s user_id=%s", session_id, user_id)
        publish_event(
            kind="observation",
            source="runtime",
            name="runtime.started",
            payload={
                "system_prompt_present": system_prompt is not None,
                "agent_role": self._agent_role,
                "parent_session_id": self._parent_session_id,
                "session_source": source,
                "model": self._model,
                "cwd": self._cwd,
            },
        )
        session = self._session_store.load(
            session_id=session_id,
            user_id=user_id,
            metadata=SessionMetadata(
                source=source,
                agent_role=self._agent_role,
                parent_session_id=self._parent_session_id,
                model=self._model,
                cwd=self._cwd,
            ),
        )

        def inject_background_notifications(iteration: int) -> None:
            if self._background_task_manager is None:
                return
            for task in self._background_task_manager.drain_completed(
                session_id=session_id,
                user_id=user_id,
            ):
                content = self._render_background_notification(task)
                self._session_store.append(session, Message(role="system", content=content))
                metadata = {
                    "task_id": task.task_id,
                    "status": task.status,
                    "description": task.description,
                }
                publish_event(
                    kind="observation",
                    source="background_task",
                    name="background_task.completed",
                    iteration=iteration,
                    item_id=task.task_id,
                    payload={**metadata, "content": content},
                )

        publish_event(
            kind="action",
            source="user",
            name="user.message",
            payload={"content": user_message},
        )
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

        def finish_cancelled(iteration: int) -> RuntimeResult:
            reason = cancellation_token.reason or "user_requested"
            self._session_store.append(
                session,
                Message(role="assistant", content=_CANCELLED_RESPONSE),
            )
            result = RuntimeResult(
                session_id=session.session_id,
                status="cancelled",
                final_response=_CANCELLED_RESPONSE,
                messages=self._session_store.snapshot(session),
                tool_results=tool_results,
            )
            error_info: dict[str, object] = {
                "error_category": "cancelled",
                "error_type": "RunCancelled",
                "error_message": reason,
                "retryable": False,
                "http_status": None,
                "error_source": "runtime",
            }
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
                attempt_count=iteration,
            )
            publish_event(
                kind="observation",
                source="runtime",
                name="runtime.cancelled",
                iteration=iteration or None,
                payload={"status": result.status, "reason": reason},
            )
            publish_event(
                kind="observation",
                source="runtime",
                name="runtime.completed",
                iteration=iteration or None,
                payload={"status": result.status, "reason": reason},
            )
            return result

        for iteration in range(self._max_iterations):
            iteration_number = iteration + 1
            if cancellation_token.is_cancelled:
                return finish_cancelled(iteration)
            logger.debug(
                "Running iteration: session_id=%s iteration=%s",
                session_id,
                iteration_number,
            )
            publish_event(
                kind="observation",
                source="runtime",
                name="iteration.started",
                iteration=iteration_number,
            )
            inject_background_notifications(iteration_number)
            model_started_at = _utc_now_iso()
            model_started_perf = perf_counter()
            session_snapshot = self._session_store.snapshot(session)
            try:
                context_result = self._context_engine.build(session_snapshot)
            except Exception as exc:
                error_info = classify_exception(exc, error_source="context").to_metadata()
                logger.exception(
                    "Runtime context build failed; continuing with uncompressed context: session_id=%s error=%s",
                    session_id,
                    exc,
                )
                context_result = ContextBuildResult(
                    messages=session_snapshot,
                    original_message_count=len(session_snapshot),
                    estimated_tokens_before=0,
                    estimated_tokens_after=0,
                    threshold_tokens=0,
                    summary_status="failed",
                )
                publish_event(
                    kind="observation",
                    source="runtime",
                    name="context.failed",
                    iteration=iteration_number,
                    payload=error_info,
                )
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
                publish_event(
                    kind="observation",
                    source="runtime",
                    name="context.compressed",
                    iteration=iteration_number,
                    payload={
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
                error_info = classify_exception(exc, error_source="model").to_metadata()
                logger.exception("Model transport failed: session_id=%s error=%s", session_id, exc)
                fallback_response = _model_failure_response(error_info)
                self._session_store.append(session, Message(role="assistant", content=fallback_response))
                publish_event(
                    kind="observation",
                    source="model",
                    name="model.failed",
                    iteration=iteration_number,
                    payload=error_info,
                )
                result = RuntimeResult(
                    session_id=session.session_id,
                    status="failed",
                    final_response=fallback_response,
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
                publish_event(
                    kind="observation",
                    source="runtime",
                    name="runtime.completed",
                    iteration=iteration_number,
                    payload={"status": result.status, **error_info},
                )
                return result
            model_calls.append(
                ModelCallTrace(
                    iteration=iteration_number,
                    response_content=response.content,
                    tool_call_names=[tool_call.name for tool_call in response.tool_calls],
                    reasoning_content=response.reasoning_content,
                    started_at=model_started_at,
                    completed_at=_utc_now_iso(),
                    duration_ms=_duration_ms(model_started_perf),
                    provider=response.provider,
                    model=response.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cache_read_tokens=response.usage.cache_read_tokens,
                    cache_write_tokens=response.usage.cache_write_tokens,
                    reasoning_tokens=response.usage.reasoning_tokens,
                    cost_usd=response.usage.cost_usd,
                )
            )
            if cancellation_token.is_cancelled:
                return finish_cancelled(iteration_number)
            publish_event(
                kind="action",
                source="agent",
                name="model.response",
                iteration=iteration_number,
                payload={
                    "content": response.content,
                    "reasoning_content": response.reasoning_content,
                    "provider": response.provider,
                    "model": response.model,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "cache_read_tokens": response.usage.cache_read_tokens,
                        "cache_write_tokens": response.usage.cache_write_tokens,
                        "reasoning_tokens": response.usage.reasoning_tokens,
                        "cost_usd": response.usage.cost_usd,
                    },
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": dict(tool_call.arguments),
                        }
                        for tool_call in response.tool_calls
                    ],
                },
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
                publish_event(
                    kind="observation",
                    source="runtime",
                    name="runtime.completed",
                    iteration=iteration_number,
                    payload={"status": result.status},
                )
                return result

            def emit_tool_output(payload: dict[str, object]) -> None:
                tool_call_id = payload.get("tool_call_id")
                publish_event(
                    kind="delta",
                    source="tool",
                    name="tool.progress",
                    iteration=iteration_number,
                    item_id=tool_call_id if isinstance(tool_call_id, str) else None,
                    payload=payload,
                )

            tool_context = ToolContext(
                session_id=session.session_id,
                user_id=user_id,
                iteration=iteration_number,
                emit_output=emit_tool_output,
            )
            for tool_call in response.tool_calls:
                publish_event(
                    kind="action",
                    source="agent",
                    name="tool.call",
                    iteration=iteration_number,
                    item_id=tool_call.id,
                    payload={
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_call.name,
                        "arguments": dict(tool_call.arguments),
                    },
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
                publish_event(
                    kind="observation",
                    source="tool",
                    name="tool.result",
                    iteration=iteration_number,
                    item_id=tool_result.tool_call_id,
                    payload={
                        "tool_call_id": tool_result.tool_call_id,
                        "tool_name": tool_result.name,
                        "status": tool_result.status,
                        "content": tool_result.content,
                        "metadata": tool_metadata,
                        "structured_content": dict(tool_result.structured_content),
                    },
                )
                self._session_store.append(
                    session,
                    Message(
                        role="tool",
                        content=self._render_tool_message(tool_result),
                        tool_call_id=tool_result.tool_call_id,
                    ),
                )
            if cancellation_token.is_cancelled:
                return finish_cancelled(iteration_number)

        logger.error("Runtime iteration limit exceeded: session_id=%s", session_id)
        self._session_store.append(
            session,
            Message(role="assistant", content=_ITERATION_LIMIT_RESPONSE),
        )
        result = RuntimeResult(
            session_id=session.session_id,
            status="iteration_limit_exceeded",
            final_response=_ITERATION_LIMIT_RESPONSE,
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
            error_info={
                "error_category": "fatal",
                "error_type": "IterationLimitExceeded",
                "error_message": "Runtime iteration limit exceeded",
                "retryable": False,
                "http_status": None,
                "error_source": "runtime",
            },
        )
        publish_event(
            kind="observation",
            source="runtime",
            name="runtime.completed",
            iteration=self._max_iterations,
            payload={"status": result.status, "error_type": "IterationLimitExceeded"},
        )
        return result

    @staticmethod
    def _render_background_notification(task: BackgroundTask) -> str:
        lines = [
            "[Background task completed]",
            f"task_id: {task.task_id}",
            f"status: {task.status}",
            f"description: {task.description}",
        ]
        if task.result is not None:
            lines.extend(
                [
                    f"tool: {task.result.name}",
                    f"tool_status: {task.result.status}",
                    "result:",
                    task.result.content,
                ]
            )
        return "\n".join(lines)

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
                agent_role=self._agent_role,
                parent_session_id=self._parent_session_id,
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
                error_source=error_info.get("error_source") if isinstance(error_info.get("error_source"), str) else None,
                attempt_count=attempt_count,
                started_at=started_at,
                completed_at=_utc_now_iso(),
                duration_ms=duration_ms,
            )
        )

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
