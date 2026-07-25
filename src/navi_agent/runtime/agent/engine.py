from __future__ import annotations

from datetime import datetime, timezone
import logging
from collections.abc import Callable, Sequence
from threading import Lock
from time import perf_counter
from uuid import uuid4

from navi_agent.errors import classify_exception
from navi_agent.logging import log_context, update_log_context
from navi_agent.tooling import ToolContext, ToolResult

from ..tasks.background import BackgroundTask, BackgroundTaskManager
from .context import ContextBuildResult, ContextEngine, LLMContextSummarizer
from ..tools.interactions import PendingInteraction
from ..models import (
    ContextCompactionCheckpoint,
    Message,
    ModelResponse,
    RuntimeResult,
    RuntimeMode,
    SessionMetadata,
    SessionSummary,
    ToolCall,
)
from .prompt import PromptBuilder
from .control import RunCancellationToken, RunCancelledError
from ..sessions.memory import InMemorySessionStore
from ..sessions.store import SessionStore
from ..tools.rendering import DefaultToolResultRenderer, ToolResultRenderer
from ..tools.registry import ToolRegistry
from ..transports import ModelRequest, ModelTransport
from navi_agent.telemetry import (
    RuntimeEventStore,
    RuntimeTrace,
    TraceBuilder,
    TraceStore,
)
from navi_agent.events import (
    EventStoreWriter,
    RuntimeEvent,
    RuntimeEventPublisher,
    RuntimeEventPublisherHealth,
    RuntimeEventSubscriber,
)

logger = logging.getLogger("navi_agent.runtime")

_ITERATION_LIMIT_RESPONSE = "任务未能在当前执行次数内完成。请缩小任务范围或补充更明确的信息后重试。"
_CANCELLED_RESPONSE = "当前任务已停止。"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _duration_ms(started_perf: float) -> int:
    return int((perf_counter() - started_perf) * 1000)


def _model_response_payload(
    response: ModelResponse,
    *,
    purpose: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
) -> dict[str, object]:
    return {
        "purpose": purpose,
        "content": response.content,
        "reasoning_content": response.reasoning_content,
        "provider": response.provider,
        "model": response.model,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
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
    }


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
        if trace_store is not None:
            self._event_publisher.subscribe(TraceBuilder(trace_store))
        if event_store is not None:
            self._event_publisher.subscribe(
                EventStoreWriter(event_store),
                critical=True,
            )
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

    def has_session(self, session_id: str, user_id: str) -> bool:
        return self._session_store.has_session(session_id, user_id)

    def list_sessions(self, user_id: str, limit: int = 10) -> list[SessionSummary]:
        return self._session_store.list_sessions(user_id, limit)

    def get_session_messages(
        self,
        session_id: str,
        user_id: str,
    ) -> list[Message]:
        if not self._session_store.has_session(session_id, user_id):
            return []
        return self._session_store.snapshot(
            ConversationState(session_id=session_id, user_id=user_id)
        )

    def list_background_tasks(
        self,
        session_id: str,
        user_id: str,
    ) -> list[BackgroundTask]:
        if self._background_task_manager is None:
            return []
        return self._background_task_manager.list(
            session_id=session_id,
            user_id=user_id,
        )

    def event_delivery_health(self) -> RuntimeEventPublisherHealth:
        return self._event_publisher.health()

    def publish_runtime_event(
        self,
        event: RuntimeEvent,
        event_subscribers: Sequence[RuntimeEventSubscriber] | None = None,
    ) -> None:
        self._event_publisher.publish(event)
        RuntimeEventPublisher(event_subscribers or ()).publish(event)

    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
        source: str = "console",
        mode: RuntimeMode = RuntimeMode.ONLINE,
        event_subscribers: Sequence[RuntimeEventSubscriber] | None = None,
        cancellation_token: RunCancellationToken | None = None,
        resume_interaction: PendingInteraction | None = None,
    ) -> RuntimeResult:
        with log_context(session_id=session_id):
            return self._run_conversation(
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                system_prompt=system_prompt,
                source=source,
                mode=mode,
                event_subscribers=event_subscribers,
                cancellation_token=cancellation_token,
                resume_interaction=resume_interaction,
            )

    def _run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
        source: str = "console",
        mode: RuntimeMode = RuntimeMode.ONLINE,
        event_subscribers: Sequence[RuntimeEventSubscriber] | None = None,
        cancellation_token: RunCancellationToken | None = None,
        resume_interaction: PendingInteraction | None = None,
    ) -> RuntimeResult:
        cancellation_token = cancellation_token or RunCancellationToken()
        run_started_at = _utc_now_iso()
        run_started_perf = perf_counter()
        run_id = uuid4().hex
        update_log_context(run_id=run_id)
        event_sequence = 0
        event_publish_lock = Lock()
        request_publisher = RuntimeEventPublisher(event_subscribers or ())
        critical_event_failures = []

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
                delivery_failures = self._event_publisher.publish(event)
                critical_event_failures.extend(
                    failure for failure in delivery_failures if failure.critical
                )
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
                "runtime_mode": mode.value,
                "model": self._model,
                "cwd": self._cwd,
                "started_at": run_started_at,
            },
        )
        session_metadata = SessionMetadata(
            source=source,
            agent_role=self._agent_role,
            parent_session_id=self._parent_session_id,
            model=self._model,
            cwd=self._cwd,
        )
        session = self._session_store.load(
            session_id=session_id,
            user_id=user_id,
            metadata=session_metadata,
        )
        self._session_store.start_run(session, run_id, session_metadata)

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
            payload={
                "content": user_message,
                "interaction_id": (
                    resume_interaction.interaction_id if resume_interaction is not None else None
                ),
            },
        )
        run_system_message = self._prompt_builder.build_run_system_message(
            user_id=user_id,
            user_message=user_message,
            system_prompt=system_prompt,
        )
        if resume_interaction is None:
            self._session_store.append(
                session,
                Message(role="user", content=user_message),
            )
            injected_skill_names = self._prompt_builder.last_injected_skill_names
        else:
            injected_skill_names = self._prompt_builder.last_injected_skill_names
        tool_results = []
        publish_event(
            kind="observation",
            source="runtime",
            name="runtime.context_ready",
            payload={
                "system_prompt": run_system_message.content,
                "injected_skill_names": list(injected_skill_names),
            },
        )

        def completion_payload(
            result: RuntimeResult,
            *,
            attempt_count: int,
            error_info: dict[str, object] | None = None,
        ) -> dict[str, object]:
            return {
                "status": result.status,
                "final_response": result.final_response,
                "attempt_count": attempt_count,
                "completed_at": _utc_now_iso(),
                "duration_ms": _duration_ms(run_started_perf),
                "trajectory_complete": not critical_event_failures,
                "trajectory_failure_count": len(critical_event_failures),
                **(error_info or {}),
            }

        def apply_trajectory_health(result: RuntimeResult) -> None:
            if not critical_event_failures:
                return
            result.trajectory_complete = False
            latest = critical_event_failures[-1]
            result.trajectory_error = (
                f"{latest.subscriber} failed while recording {latest.event_name}: "
                f"{latest.error}"
            )
            logger.error(
                "Runtime trajectory incomplete: session_id=%s failures=%s last_subscriber=%s last_event=%s",
                session_id,
                len(critical_event_failures),
                latest.subscriber,
                latest.event_name,
            )

        def finalization_reason(result: RuntimeResult, default: str | None = None) -> str:
            if not result.trajectory_complete:
                return "trajectory_incomplete"
            return default or result.status

        def finish_result(
            result: RuntimeResult,
            *,
            iteration: int,
            attempt_count: int,
            error_info: dict[str, object] | None = None,
            end_reason: str | None = None,
            failure_reason: str | None = None,
        ) -> RuntimeResult:
            publish_event(
                kind="observation",
                source="runtime",
                name="runtime.completed",
                iteration=iteration or None,
                payload=completion_payload(
                    result,
                    attempt_count=attempt_count,
                    error_info=error_info,
                ),
            )
            apply_trajectory_health(result)
            self._session_store.finalize(
                session,
                run_id,
                status=result.status,
                end_reason=finalization_reason(result, end_reason),
                trajectory_complete=result.trajectory_complete,
                failure_reason=result.trajectory_error or failure_reason,
            )
            return result

        def finish_cancelled(iteration: int) -> RuntimeResult:
            reason = cancellation_token.reason or "user_requested"
            superseded = reason == "user_steer"
            if not superseded:
                self._session_store.append(
                    session,
                    Message(role="assistant", content=_CANCELLED_RESPONSE),
                )
            result = RuntimeResult(
                session_id=session.session_id,
                status="superseded" if superseded else "cancelled",
                final_response="" if superseded else _CANCELLED_RESPONSE,
                run_id=run_id,
                messages=self._session_store.snapshot(session),
                tool_results=tool_results,
            )
            error_info: dict[str, object] = {
                "error_category": "cancelled",
                "error_type": "RunSuperseded" if superseded else "RunCancelled",
                "error_message": reason,
                "retryable": False,
                "http_status": None,
                "error_source": "runtime",
            }
            publish_event(
                kind="observation",
                source="runtime",
                name="runtime.superseded" if superseded else "runtime.cancelled",
                iteration=iteration or None,
                payload={"status": result.status, "reason": reason},
            )
            return finish_result(
                result,
                iteration=iteration,
                attempt_count=iteration,
                error_info=error_info,
                end_reason=reason,
            )

        def finish_waiting(iteration: int, pending_result) -> RuntimeResult:
            prompt = pending_result.structured_content.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                prompt = pending_result.content
            result = RuntimeResult(
                session_id=session.session_id,
                status="awaiting_input",
                final_response=prompt,
                run_id=run_id,
                messages=self._session_store.snapshot(session),
                tool_results=tool_results,
            )
            payload = {
                "status": result.status,
                "interaction_id": pending_result.structured_content.get("interaction_id"),
                "interaction_kind": pending_result.structured_content.get("interaction_kind"),
                "prompt": prompt,
            }
            publish_event(
                kind="observation",
                source="runtime",
                name="runtime.waiting",
                iteration=iteration,
                item_id=pending_result.tool_call_id,
                payload=payload,
            )
            return finish_result(
                result,
                iteration=iteration,
                attempt_count=iteration,
            )

        def record_tool_result(
            tool_result: ToolResult,
            *,
            iteration: int,
            arguments: dict[str, object],
            checkpoint_run_id: str = run_id,
            persist_message: bool = True,
        ) -> None:
            tool_metadata, tool_started_at, tool_completed_at, tool_duration_ms = _pop_trace_timing(
                dict(tool_result.metadata)
            )
            logger.debug(
                "Tool executed: session_id=%s tool=%s",
                session_id,
                tool_result.name,
            )
            tool_results.append(tool_result)
            error_info = _classify_tool_error(
                tool_result=tool_result,
                tool_metadata=tool_metadata,
            )
            self._session_store.complete_tool_call(
                session,
                checkpoint_run_id,
                tool_result,
            )
            publish_event(
                kind="observation",
                source="tool",
                name="tool.result",
                iteration=iteration,
                item_id=tool_result.tool_call_id,
                payload={
                    "tool_call_id": tool_result.tool_call_id,
                    "tool_name": tool_result.name,
                    "status": tool_result.status,
                    "arguments": arguments,
                    "content": tool_result.content,
                    "metadata": tool_metadata,
                    "structured_content": dict(tool_result.structured_content),
                    "started_at": tool_started_at,
                    "completed_at": tool_completed_at,
                    "duration_ms": tool_duration_ms,
                    **error_info,
                },
            )
            if persist_message:
                self._session_store.append(
                    session,
                    Message(
                        role="tool",
                        content=self._render_tool_message(tool_result),
                        tool_call_id=tool_result.tool_call_id,
                        tool_name=tool_result.name,
                    ),
                )

        if resume_interaction is not None:
            if not resume_interaction.tool_call_id or not resume_interaction.tool_name:
                raise ValueError("pending interaction is missing its tool-call checkpoint")
            publish_event(
                kind="observation",
                source="runtime",
                name="runtime.resumed",
                item_id=resume_interaction.tool_call_id,
                payload={
                    "interaction_id": resume_interaction.interaction_id,
                    "interaction_kind": resume_interaction.kind,
                    "resolution": resume_interaction.status,
                },
            )
            resumed_call = ToolCall(
                id=resume_interaction.tool_call_id,
                name=resume_interaction.tool_name,
                arguments=dict(resume_interaction.arguments or {}),
            )
            resumed_context = ToolContext(
                session_id=session.session_id,
                user_id=user_id,
                iteration=0,
                run_id=run_id,
                cancellation_requested=lambda: cancellation_token.is_cancelled,
            )
            checkpoint_run_id = resume_interaction.run_id or run_id
            self._session_store.start_tool_call(
                session,
                checkpoint_run_id,
                resumed_call,
            )
            resumed_result = self._session_store.get_tool_result(
                checkpoint_run_id,
                resumed_call.id,
            )
            if resumed_result is not None:
                resumed_result.metadata["deduplicated"] = True
            elif resume_interaction.kind == "approval" and resume_interaction.status == "approved":
                resumed_result = self._tool_registry.dispatch_approved(
                    resumed_call,
                    context=resumed_context,
                    enabled_toolsets=self._enabled_toolsets,
                    disabled_toolsets=self._disabled_toolsets,
                )
            elif resume_interaction.kind == "clarification":
                resumed_result = ToolResult.ok(
                    name=resume_interaction.tool_name,
                    content=resume_interaction.response or user_message,
                    structured_content={
                        "interaction_id": resume_interaction.interaction_id,
                        "interaction_resumed": True,
                    },
                ).bind(resume_interaction.tool_call_id)
            else:
                resumed_result = ToolResult.error(
                    name=resume_interaction.tool_name,
                    content="User denied the pending tool request.",
                    structured_content={
                        "interaction_id": resume_interaction.interaction_id,
                        "interaction_denied": True,
                    },
                ).bind(resume_interaction.tool_call_id)
            record_tool_result(
                resumed_result,
                iteration=0,
                arguments=dict(resume_interaction.arguments or {}),
                checkpoint_run_id=checkpoint_run_id,
            )

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
            session_snapshot = self._session_store.snapshot(session)
            checkpoint = self._session_store.load_compaction_checkpoint(session)
            try:
                context_result = self._context_engine.build(
                    session_snapshot,
                    checkpoint=checkpoint,
                    prefix_messages=[run_system_message],
                )
            except Exception as exc:
                error_info = classify_exception(exc, error_source="context").to_metadata()
                logger.exception(
                    "Runtime context build failed; continuing with uncompressed context: session_id=%s error=%s",
                    session_id,
                    exc,
                )
                context_result = ContextBuildResult(
                    messages=[run_system_message, *session_snapshot],
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
            if context_result.summary_call is not None:
                summary_call = context_result.summary_call
                self._session_store.record_model_response(
                    session,
                    run_id,
                    summary_call.response,
                )
                publish_event(
                    kind="action",
                    source="context",
                    name="model.response",
                    iteration=iteration_number,
                    item_id=f"context-summary:{iteration_number}",
                    payload=_model_response_payload(
                        summary_call.response,
                        purpose="context_summary",
                        started_at=summary_call.started_at,
                        completed_at=summary_call.completed_at,
                        duration_ms=summary_call.duration_ms,
                    ),
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
            if context_result.checkpoint is not None:
                self._session_store.save_compaction_checkpoint(
                    session,
                    ContextCompactionCheckpoint(
                        session_id=session.session_id,
                        covered_message_count=context_result.checkpoint.covered_message_count,
                        protected_head_count=context_result.checkpoint.protected_head_count,
                        source_hash=context_result.checkpoint.source_hash,
                        summary=context_result.checkpoint.summary,
                        model=self._model,
                    ),
                )
            try:
                model_item_id = f"model:{iteration_number}"
                model_started_at = _utc_now_iso()
                model_started_perf = perf_counter()
                model_request = ModelRequest(
                    messages=context_result.messages,
                    tools=self._tool_registry.schemas(
                        enabled_toolsets=self._enabled_toolsets,
                        disabled_toolsets=self._disabled_toolsets,
                    ),
                    cancellation_requested=lambda: cancellation_token.is_cancelled,
                )
                generate_stream = getattr(self._transport, "generate_stream", None)
                if callable(generate_stream):
                    def publish_text_delta(delta: str) -> None:
                        publish_event(
                            kind="delta",
                            source="model",
                            name="model.delta",
                            iteration=iteration_number,
                            item_id=model_item_id,
                            payload={"delta": delta},
                        )

                    response = generate_stream(model_request, publish_text_delta)
                else:
                    response = self._transport.generate(model_request)
            except RunCancelledError:
                return finish_cancelled(iteration_number)
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
                    run_id=run_id,
                    messages=self._session_store.snapshot(session),
                    tool_results=tool_results,
                )
                return finish_result(
                    result,
                    iteration=iteration_number,
                    attempt_count=iteration_number,
                    error_info=error_info,
                    end_reason=str(error_info["error_type"]),
                    failure_reason=str(error_info["error_message"]),
                )
            model_payload = _model_response_payload(
                response,
                purpose="agent",
                started_at=model_started_at,
                completed_at=_utc_now_iso(),
                duration_ms=_duration_ms(model_started_perf),
            )
            self._session_store.record_model_response(session, run_id, response)
            if cancellation_token.is_cancelled:
                publish_event(
                    kind="observation",
                    source="model",
                    name="model.discarded",
                    iteration=iteration_number,
                    item_id=model_item_id,
                    payload=model_payload,
                )
                return finish_cancelled(iteration_number)
            if response.tool_calls:
                publish_event(
                    kind="observation",
                    source="model",
                    name="model.plan",
                    iteration=iteration_number,
                    item_id=model_item_id,
                    payload={"tool_calls": model_payload["tool_calls"]},
                )
            publish_event(
                kind="action",
                source="agent",
                name="model.response",
                iteration=iteration_number,
                item_id=model_item_id,
                payload=model_payload,
            )

            assistant_message = Message(
                role="assistant",
                content=response.content,
                reasoning_content=response.reasoning_content,
                tool_calls=response.tool_calls,
                provider=response.provider,
                model=response.model,
                token_count=response.usage.output_tokens,
                finish_reason=response.finish_reason,
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
                    run_id=run_id,
                    messages=self._session_store.snapshot(session),
                    tool_results=tool_results,
                )
                return finish_result(
                    result,
                    iteration=iteration_number,
                    attempt_count=iteration_number,
                )

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
                run_id=run_id,
                emit_output=emit_tool_output,
                cancellation_requested=lambda: cancellation_token.is_cancelled,
            )
            unique_tool_calls = []
            seen_tool_call_ids = set()
            for tool_call in response.tool_calls:
                if tool_call.id in seen_tool_call_ids:
                    continue
                seen_tool_call_ids.add(tool_call.id)
                unique_tool_calls.append(tool_call)

            pending_tool_calls = []
            completed_tool_results = {}
            for tool_call in unique_tool_calls:
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
                self._session_store.start_tool_call(session, run_id, tool_call)
                completed_result = self._session_store.get_tool_result(run_id, tool_call.id)
                if completed_result is None:
                    pending_tool_calls.append(tool_call)
                else:
                    completed_result.metadata["deduplicated"] = True
                    completed_tool_results[tool_call.id] = completed_result

            dispatched_results = self._tool_registry.dispatch(
                pending_tool_calls,
                context=tool_context,
                enabled_toolsets=self._enabled_toolsets,
                disabled_toolsets=self._disabled_toolsets,
            )
            completed_tool_results.update(
                {tool_result.tool_call_id: tool_result for tool_result in dispatched_results}
            )
            for tool_call in unique_tool_calls:
                tool_result = completed_tool_results[tool_call.id]
                record_tool_result(
                    tool_result,
                    iteration=iteration_number,
                    arguments=dict(tool_call.arguments),
                    persist_message=(
                        tool_result.structured_content.get("interaction_pending") is not True
                    ),
                )
            if cancellation_token.is_cancelled:
                return finish_cancelled(iteration_number)
            pending_result = next(
                (
                    item
                    for item in tool_results
                    if item.structured_content.get("interaction_pending") is True
                ),
                None,
            )
            if pending_result is not None:
                return finish_waiting(iteration_number, pending_result)

        logger.error("Runtime iteration limit exceeded: session_id=%s", session_id)
        self._session_store.append(
            session,
            Message(role="assistant", content=_ITERATION_LIMIT_RESPONSE),
        )
        result = RuntimeResult(
            session_id=session.session_id,
            status="iteration_limit_exceeded",
            final_response=_ITERATION_LIMIT_RESPONSE,
            run_id=run_id,
            messages=self._session_store.snapshot(session),
            tool_results=tool_results,
        )
        error_info = {
            "error_category": "fatal",
            "error_type": "IterationLimitExceeded",
            "error_message": "Runtime iteration limit exceeded",
            "retryable": False,
            "http_status": None,
            "error_source": "runtime",
        }
        return finish_result(
            result,
            iteration=self._max_iterations,
            attempt_count=self._max_iterations,
            error_info=error_info,
            end_reason=str(error_info["error_type"]),
            failure_reason=str(error_info["error_message"]),
        )

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
