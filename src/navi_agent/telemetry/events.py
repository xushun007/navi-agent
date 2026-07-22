from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from threading import Lock
from typing import Protocol

from navi_agent.events import RuntimeEvent


class RuntimeEventStore(Protocol):
    def record(self, event: RuntimeEvent) -> None: ...

    def list_events(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RuntimeEvent]: ...


class InMemoryRuntimeEventStore:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def record(self, event: RuntimeEvent) -> None:
        self.events.append(event)

    def list_events(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RuntimeEvent]:
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

    def record(self, event: RuntimeEvent) -> None:
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
    ) -> list[RuntimeEvent]:
        if not self._path.exists():
            return []
        events: list[RuntimeEvent] = []
        with self._lock:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if "payload" in data and "metadata" not in data:
                        data["metadata"] = data.pop("payload")
                    events.append(RuntimeEvent(**data))
        if session_id is not None:
            events = [event for event in events if event.session_id == session_id]
        if run_id is not None:
            events = [event for event in events if event.run_id == run_id]
        return sorted(events, key=lambda event: (event.timestamp, event.sequence))
