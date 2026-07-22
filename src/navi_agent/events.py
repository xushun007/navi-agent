from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Protocol
from uuid import uuid4

logger = logging.getLogger("navi_agent.events")


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    session_id: str
    user_id: str
    run_id: str
    sequence: int
    kind: str
    source: str
    name: str
    event_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int | None = None
    item_id: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def payload(self) -> dict[str, Any]:
        """Compatibility view for existing telemetry consumers."""
        return self.metadata


class RuntimeEventSubscriber(Protocol):
    def handle(self, event: RuntimeEvent) -> None: ...


class RuntimeEventPublisher:
    def __init__(self, subscribers: Iterable[RuntimeEventSubscriber] = ()) -> None:
        self._subscribers = list(subscribers)

    def subscribe(self, subscriber: RuntimeEventSubscriber) -> None:
        self._subscribers.append(subscriber)

    def publish(self, event: RuntimeEvent) -> None:
        for subscriber in self._subscribers:
            try:
                subscriber.handle(event)
            except Exception:
                logger.exception(
                    "Runtime event subscriber failed: subscriber=%s event=%s event_id=%s",
                    type(subscriber).__name__,
                    event.name,
                    event.event_id,
                )


class RuntimeEventRecorder(Protocol):
    def record(self, event: RuntimeEvent) -> None: ...


class EventStoreWriter:
    def __init__(self, store: RuntimeEventRecorder) -> None:
        self._store = store

    def handle(self, event: RuntimeEvent) -> None:
        if event.kind == "delta":
            return
        self._store.record(event)


class CallableEventSubscriber:
    def __init__(self, callback: Callable[[RuntimeEvent], None]) -> None:
        self._callback = callback

    def handle(self, event: RuntimeEvent) -> None:
        self._callback(event)
