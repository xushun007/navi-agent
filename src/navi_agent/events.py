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
    """Authoritative immutable fact emitted by one runtime execution."""

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


@dataclass(frozen=True, slots=True)
class RuntimeEventDeliveryFailure:
    subscriber: str
    event_name: str
    event_id: str
    critical: bool
    error: str


@dataclass(frozen=True, slots=True)
class RuntimeEventPublisherHealth:
    critical_failure_count: int
    optional_failure_count: int
    last_failure: RuntimeEventDeliveryFailure | None

    @property
    def healthy(self) -> bool:
        return self.critical_failure_count == 0


@dataclass(frozen=True, slots=True)
class _SubscriberRegistration:
    subscriber: RuntimeEventSubscriber
    critical: bool = False


class RuntimeEventPublisher:
    def __init__(self, subscribers: Iterable[RuntimeEventSubscriber] = ()) -> None:
        self._subscribers = [
            _SubscriberRegistration(subscriber=subscriber)
            for subscriber in subscribers
        ]
        self._critical_failure_count = 0
        self._optional_failure_count = 0
        self._last_failure: RuntimeEventDeliveryFailure | None = None

    def subscribe(
        self,
        subscriber: RuntimeEventSubscriber,
        *,
        critical: bool = False,
    ) -> None:
        self._subscribers.append(
            _SubscriberRegistration(
                subscriber=subscriber,
                critical=critical,
            )
        )

    def publish(self, event: RuntimeEvent) -> list[RuntimeEventDeliveryFailure]:
        failures: list[RuntimeEventDeliveryFailure] = []
        for registration in self._subscribers:
            try:
                registration.subscriber.handle(event)
            except Exception as error:
                failure = RuntimeEventDeliveryFailure(
                    subscriber=type(registration.subscriber).__name__,
                    event_name=event.name,
                    event_id=event.event_id,
                    critical=registration.critical,
                    error=str(error),
                )
                failures.append(failure)
                self._last_failure = failure
                if registration.critical:
                    self._critical_failure_count += 1
                else:
                    self._optional_failure_count += 1
                logger.exception(
                    "Runtime event subscriber failed: subscriber=%s critical=%s event=%s event_id=%s",
                    failure.subscriber,
                    failure.critical,
                    event.name,
                    event.event_id,
                )
        return failures

    def health(self) -> RuntimeEventPublisherHealth:
        return RuntimeEventPublisherHealth(
            critical_failure_count=self._critical_failure_count,
            optional_failure_count=self._optional_failure_count,
            last_failure=self._last_failure,
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
