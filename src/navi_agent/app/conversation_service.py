from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from navi_agent.events import (
    RuntimeEvent,
    RuntimeEventPublisher,
    RuntimeEventSubscriber,
)
from navi_agent.runtime import (
    ActiveRunRegistry,
    AgentRuntime,
    BackgroundTask,
    JsonPendingInteractionStore,
    PendingInteraction,
    RuntimeMode,
    RuntimeResult,
    RuntimeRunState,
    RunStateTracker,
)


@dataclass(slots=True)
class AppRequest:
    user_id: str
    message: str
    session_id: str | None = None
    system_prompt: str | None = None
    mode: RuntimeMode = RuntimeMode.ONLINE
    source: str = "console"


class ConversationService:
    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        default_system_prompt: str | None = None,
        interaction_store: JsonPendingInteractionStore | None = None,
        before_online_run: Callable[[str, str], None] | None = None,
        after_online_run: Callable[[RuntimeResult, str, str], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._active_runs = ActiveRunRegistry()
        self._run_states = RunStateTracker()
        self._default_system_prompt = default_system_prompt
        self._interaction_store = interaction_store
        self._before_online_run = before_online_run or (lambda _session_id, _user_id: None)
        self._after_online_run = (
            after_online_run or (lambda **_kwargs: None)
        )

    def handle(
        self,
        request: AppRequest,
        *,
        event_subscribers: list[RuntimeEventSubscriber] | None = None,
    ) -> RuntimeResult:
        session_id = request.session_id or self._new_session_id()
        system_prompt = request.system_prompt
        if system_prompt is None:
            system_prompt = self._default_system_prompt

        resume_interaction = None
        if self._interaction_store is not None:
            self._publish_expired_interactions(
                session_id=session_id,
                event_subscribers=event_subscribers,
            )
            pending = self._interaction_store.get_pending(session_id)
            if pending is not None and pending.kind == "clarification":
                self._interaction_store.resolve_clarification(
                    session_id,
                    response=request.message,
                )
            resume_interaction = self._interaction_store.get_resolved(session_id)

        if request.mode is RuntimeMode.ONLINE:
            self._before_online_run(session_id, request.user_id)
        cancellation_token = self._active_runs.start(session_id)
        try:
            result = self._runtime.run_conversation(
                session_id=session_id,
                user_id=request.user_id,
                user_message=request.message,
                system_prompt=system_prompt,
                source=request.source,
                mode=request.mode,
                event_subscribers=[self._run_states, *(event_subscribers or [])],
                cancellation_token=cancellation_token,
                resume_interaction=resume_interaction,
            )
        finally:
            self._active_runs.finish(session_id, cancellation_token)
        if self._interaction_store is not None and result.status == "awaiting_input":
            self._attach_pending_tool_call(result)
        if self._interaction_store is not None and resume_interaction is not None:
            self._interaction_store.complete(resume_interaction.interaction_id)
        if request.mode is RuntimeMode.ONLINE:
            self._after_online_run(
                result=result,
                session_id=result.session_id,
                user_id=request.user_id,
            )
        return result

    def cancel_session(self, session_id: str, *, reason: str = "user_requested") -> bool:
        return self._active_runs.cancel(session_id, reason)

    def is_session_active(self, session_id: str) -> bool:
        return self._active_runs.is_active(session_id)

    def get_run_state(self, session_id: str) -> RuntimeRunState | None:
        return self._run_states.get(session_id)

    def resolve_interaction(
        self,
        session_id: str,
        *,
        approved: bool,
    ) -> PendingInteraction | None:
        if self._interaction_store is None:
            return None
        self._publish_expired_interactions(session_id=session_id)
        return self._interaction_store.resolve(session_id, approved=approved)

    def _publish_expired_interactions(
        self,
        *,
        session_id: str,
        event_subscribers: list[RuntimeEventSubscriber] | None = None,
    ) -> None:
        if self._interaction_store is None:
            return
        subscribers = [self._run_states, *(event_subscribers or [])]
        for interaction in self._interaction_store.expire(session_id):
            event = RuntimeEvent(
                session_id=interaction.session_id,
                user_id=interaction.user_id,
                run_id=f"interaction:{interaction.interaction_id}",
                sequence=1,
                kind="observation",
                source="runtime",
                name="runtime.interaction_expired",
                item_id=interaction.interaction_id,
                metadata={
                    "status": "expired",
                    "interaction_id": interaction.interaction_id,
                    "interaction_kind": interaction.kind,
                    "origin_run_id": interaction.run_id,
                    "reason": "interaction_ttl_elapsed",
                },
            )
            publish = getattr(self._runtime, "publish_runtime_event", None)
            if callable(publish):
                publish(event, subscribers)
            else:
                RuntimeEventPublisher(subscribers).publish(event)

    def _attach_pending_tool_call(self, result: RuntimeResult) -> None:
        if self._interaction_store is None:
            return
        pending_result = next(
            (
                item
                for item in result.tool_results
                if item.structured_content.get("interaction_pending") is True
            ),
            None,
        )
        if pending_result is None:
            return
        interaction_id = pending_result.structured_content.get("interaction_id")
        if not isinstance(interaction_id, str) or not interaction_id:
            return
        tool_call = next(
            (
                tool_call
                for message in reversed(result.messages)
                for tool_call in message.tool_calls
                if tool_call.id == pending_result.tool_call_id
            ),
            None,
        )
        if tool_call is None:
            return
        self._interaction_store.attach_tool_call(
            interaction_id,
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
        )


    def add_background_task_listener(
        self,
        listener: Callable[[BackgroundTask], None],
    ) -> bool:
        return self._runtime.add_background_task_listener(listener)

    @staticmethod
    def _new_session_id() -> str:
        return uuid4().hex
