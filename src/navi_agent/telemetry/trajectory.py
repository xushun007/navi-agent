from __future__ import annotations

from dataclasses import dataclass
import json

from navi_agent.events import RuntimeEvent

from .events import RuntimeEventStore


@dataclass(frozen=True, slots=True)
class RuntimeTrajectory:
    session_id: str
    run_id: str | None
    events: list[RuntimeEvent]

    @property
    def empty(self) -> bool:
        return not self.events


class RuntimeTrajectoryService:
    def __init__(self, event_store: RuntimeEventStore) -> None:
        self._event_store = event_store

    def load(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
    ) -> RuntimeTrajectory:
        events = self._event_store.list_events(session_id=session_id, run_id=run_id)
        return RuntimeTrajectory(session_id=session_id, run_id=run_id, events=events)

    def render(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
    ) -> str:
        trajectory = self.load(session_id=session_id, run_id=run_id)
        if trajectory.empty:
            return f"runtime_trajectory: none\nsession_id: {session_id}"
        lines = [
            "runtime_trajectory:",
            f"session_id: {trajectory.session_id}",
            f"run_id: {trajectory.events[0].run_id if run_id is None else run_id}",
        ]
        for event in trajectory.events:
            lines.append(_render_event(event))
        return "\n".join(lines)


def _render_event(event: RuntimeEvent) -> str:
    prefix = f"[{event.sequence}] {event.kind}/{event.source} {event.name}"
    if event.iteration is not None:
        prefix = f"{prefix} iter={event.iteration}"
    summary = _event_summary(event)
    return f"{prefix}: {summary}" if summary else prefix


def _event_summary(event: RuntimeEvent) -> str:
    payload = event.payload
    if event.name == "user.message":
        return _compact(str(payload.get("content") or ""))
    if event.name == "model.response":
        tool_calls = payload.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            names = [
                str(item.get("name"))
                for item in tool_calls
                if isinstance(item, dict) and item.get("name")
            ]
            return f"tool_calls=[{', '.join(names)}]"
        return _compact(str(payload.get("content") or ""))
    if event.name == "tool.call":
        tool_name = str(payload.get("tool_name") or "unknown")
        arguments = payload.get("arguments")
        if isinstance(arguments, dict) and arguments:
            rendered_arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
            return f"{tool_name} args={_compact(rendered_arguments)}"
        return tool_name
    if event.name == "tool.result":
        tool_name = str(payload.get("tool_name") or "unknown")
        status = str(payload.get("status") or "unknown")
        return f"{tool_name} {status}"
    if event.name == "runtime.completed":
        return f"status={payload.get('status') or 'unknown'}"
    if event.name.endswith(".failed"):
        error_type = payload.get("error_type") or "unknown"
        retryable = payload.get("retryable")
        return f"error_type={error_type} retryable={retryable}"
    return ""


def _compact(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"
