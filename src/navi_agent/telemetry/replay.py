from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from .models import RuntimeTrace
from .store import TraceStore

if TYPE_CHECKING:
    from navi_agent.runtime.models import RuntimeResult


class ReplayRuntime(Protocol):
    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> RuntimeResult: ...


@dataclass(slots=True)
class TraceReplayResult:
    source_trace: RuntimeTrace
    replay_session_id: str
    runtime_result: RuntimeResult


class TraceReplayService:
    def __init__(
        self,
        runtime: ReplayRuntime,
        trace_store: TraceStore,
    ) -> None:
        self._runtime = runtime
        self._trace_store = trace_store

    def replay_trace(
        self,
        trace: RuntimeTrace,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        system_prompt: str | None = None,
    ) -> TraceReplayResult:
        replay_session_id = session_id or self._new_replay_session_id(trace.session_id)
        replay_user_id = user_id or trace.user_id
        replay_system_prompt = system_prompt if system_prompt is not None else trace.system_prompt

        result = self._runtime.run_conversation(
            session_id=replay_session_id,
            user_id=replay_user_id,
            user_message=trace.user_message,
            system_prompt=replay_system_prompt,
        )
        return TraceReplayResult(
            source_trace=trace,
            replay_session_id=replay_session_id,
            runtime_result=result,
        )

    def replay_latest(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        system_prompt: str | None = None,
    ) -> TraceReplayResult:
        trace = self._trace_store.get_latest_trace(
            session_id=session_id,
            user_id=user_id,
        )
        if trace is None:
            raise ValueError("No trace available for replay")
        return self.replay_trace(
            trace,
            user_id=user_id,
            system_prompt=system_prompt,
        )

    @staticmethod
    def _new_replay_session_id(source_session_id: str) -> str:
        return f"{source_session_id}:replay:{uuid4().hex[:8]}"
