from navi_agent.events import EventStoreWriter, RuntimeEvent, RuntimeEventPublisher


class RecordingSubscriber:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def handle(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class FailingSubscriber:
    def handle(self, event: RuntimeEvent) -> None:
        raise RuntimeError("subscriber unavailable")


def _event() -> RuntimeEvent:
    return RuntimeEvent(
        session_id="s1",
        user_id="u1",
        run_id="r1",
        sequence=1,
        kind="observation",
        source="runtime",
        name="runtime.started",
    )


def test_publisher_delivers_events_to_all_subscribers() -> None:
    first = RecordingSubscriber()
    second = RecordingSubscriber()
    publisher = RuntimeEventPublisher([first, second])

    publisher.publish(_event())

    assert [event.name for event in first.events] == ["runtime.started"]
    assert [event.name for event in second.events] == ["runtime.started"]


def test_publisher_isolates_subscriber_failures() -> None:
    recording = RecordingSubscriber()
    publisher = RuntimeEventPublisher([FailingSubscriber(), recording])

    publisher.publish(_event())

    assert [event.name for event in recording.events] == ["runtime.started"]
    assert publisher.health().healthy
    assert publisher.health().optional_failure_count == 1


def test_publisher_tracks_critical_subscriber_failures() -> None:
    publisher = RuntimeEventPublisher()
    publisher.subscribe(FailingSubscriber(), critical=True)

    failures = publisher.publish(_event())

    assert len(failures) == 1
    assert failures[0].critical
    assert not publisher.health().healthy
    assert publisher.health().critical_failure_count == 1
    assert publisher.health().last_failure == failures[0]


def test_event_store_writer_skips_ephemeral_deltas() -> None:
    class Store:
        def __init__(self) -> None:
            self.events: list[RuntimeEvent] = []

        def record(self, event: RuntimeEvent) -> None:
            self.events.append(event)

    store = Store()
    writer = EventStoreWriter(store)
    event = _event()
    delta = RuntimeEvent(
        session_id="s1",
        user_id="u1",
        run_id="r1",
        sequence=2,
        kind="delta",
        source="tool",
        name="tool.progress",
    )

    writer.handle(event)
    writer.handle(delta)

    assert store.events == [event]
