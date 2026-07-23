from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from navi_agent.events import RuntimeEvent


@dataclass(frozen=True, slots=True)
class RuntimeRunState:
    session_id: str
    user_id: str
    run_id: str
    status: str
    updated_at: str
    interaction_id: str | None = None
    reason: str | None = None


class RunStateTracker:
    """Maintains the latest queryable run state as a RuntimeEvent projection."""

    def __init__(self) -> None:
        self._states: dict[str, RuntimeRunState] = {}
        self._lock = Lock()

    def handle(self, event: RuntimeEvent) -> None:
        status = _project_status(event)
        if status is None:
            return
        interaction_id = event.metadata.get("interaction_id")
        reason = event.metadata.get("reason")
        with self._lock:
            previous = self._states.get(event.session_id)
        if previous is not None and previous.run_id == event.run_id:
            if not isinstance(interaction_id, str):
                interaction_id = previous.interaction_id
            if not isinstance(reason, str):
                reason = previous.reason
        state = RuntimeRunState(
            session_id=event.session_id,
            user_id=event.user_id,
            run_id=event.run_id,
            status=status,
            updated_at=event.timestamp,
            interaction_id=interaction_id if isinstance(interaction_id, str) else None,
            reason=reason if isinstance(reason, str) else None,
        )
        with self._lock:
            self._states[event.session_id] = state

    def get(self, session_id: str) -> RuntimeRunState | None:
        with self._lock:
            return self._states.get(session_id)


def _project_status(event: RuntimeEvent) -> str | None:
    if event.name == "runtime.started":
        return "running"
    if event.name == "runtime.resumed":
        return "resumed"
    if event.name == "runtime.waiting":
        return "awaiting_input"
    if event.name == "runtime.cancelled":
        return "cancelled"
    if event.name == "runtime.interaction_expired":
        return "expired"
    if event.name != "runtime.completed":
        return None
    return {
        "success": "completed",
        "cancelled": "cancelled",
        "awaiting_input": "awaiting_input",
    }.get(str(event.metadata.get("status")), "failed")
