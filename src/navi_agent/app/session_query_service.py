from __future__ import annotations

from navi_agent.runtime import AgentRuntime, BackgroundTask, Message, SessionSummary
from navi_agent.telemetry import RuntimeTrace


class SessionQueryService:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    def get_latest_trace(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> RuntimeTrace | None:
        return self._runtime.get_latest_trace(
            session_id=session_id,
            user_id=user_id,
        )

    def has_session(self, session_id: str, user_id: str) -> bool:
        return self._runtime.has_session(session_id, user_id)

    def list_sessions(self, user_id: str, limit: int = 10) -> list[SessionSummary]:
        return self._runtime.list_sessions(user_id, limit)

    def get_session_messages(
        self,
        session_id: str,
        user_id: str,
    ) -> list[Message]:
        return self._runtime.get_session_messages(session_id, user_id)

    def list_background_tasks(
        self,
        session_id: str,
        user_id: str,
    ) -> list[BackgroundTask]:
        return self._runtime.list_background_tasks(session_id, user_id)

    def get_session_traces(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
    ) -> list[RuntimeTrace]:
        return self._runtime.get_session_traces(
            session_id=session_id,
            user_id=user_id,
        )
