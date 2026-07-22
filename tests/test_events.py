from navi_agent.events import RuntimeEvent, RuntimeEventPublisher


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
