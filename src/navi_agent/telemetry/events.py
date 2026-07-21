from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RuntimeStreamEvent:
    session_id: str
    user_id: str
    run_id: str
    sequence: int
    kind: str
    source: str
    name: str
    event_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    payload: dict[str, Any] = field(default_factory=dict)


class RuntimeEventStore(Protocol):
    def record(self, event: RuntimeStreamEvent) -> None: ...

    def list_events(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RuntimeStreamEvent]: ...


class InMemoryRuntimeEventStore:
    def __init__(self) -> None:
        self.events: list[RuntimeStreamEvent] = []

    def record(self, event: RuntimeStreamEvent) -> None:
        self.events.append(event)

    def list_events(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RuntimeStreamEvent]:
        events = list(self.events)
        if session_id is not None:
            events = [event for event in events if event.session_id == session_id]
        if run_id is not None:
            events = [event for event in events if event.run_id == run_id]
        return sorted(events, key=lambda event: (event.timestamp, event.sequence))


class JsonlRuntimeEventStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()

    def record(self, event: RuntimeStreamEvent) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def list_events(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RuntimeStreamEvent]:
        if not self._path.exists():
            return []
        events: list[RuntimeStreamEvent] = []
        with self._lock:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    events.append(RuntimeStreamEvent(**json.loads(line)))
        if session_id is not None:
            events = [event for event in events if event.session_id == session_id]
        if run_id is not None:
            events = [event for event in events if event.run_id == run_id]
        return sorted(events, key=lambda event: (event.timestamp, event.sequence))
