from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from navi_agent.runtime import AgentRuntime, RuntimeResult


@dataclass(slots=True)
class AppRequest:
    user_id: str
    message: str
    session_id: str | None = None
    system_prompt: str | None = None


class ApplicationService:
    def __init__(
        self,
        runtime: AgentRuntime,
        default_system_prompt: str | None = None,
    ) -> None:
        self._runtime = runtime
        self._default_system_prompt = default_system_prompt

    def handle(self, request: AppRequest) -> RuntimeResult:
        session_id = request.session_id or self._new_session_id()
        system_prompt = request.system_prompt
        if system_prompt is None:
            system_prompt = self._default_system_prompt

        return self._runtime.run_conversation(
            session_id=session_id,
            user_id=request.user_id,
            user_message=request.message,
            system_prompt=system_prompt,
        )

    @staticmethod
    def _new_session_id() -> str:
        return uuid4().hex
