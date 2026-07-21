from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from navi_agent.telemetry import JsonlRuntimeEventStore, RuntimeStreamEvent


class RuntimeEventStoreTests(unittest.TestCase):
    def test_jsonl_event_store_appends_and_filters_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            store = JsonlRuntimeEventStore(path)
            store.record(
                RuntimeStreamEvent(
                    session_id="s1",
                    user_id="u1",
                    run_id="r1",
                    sequence=1,
                    kind="action",
                    source="user",
                    name="user.message",
                    payload={"content": "hello"},
                )
            )
            store.record(
                RuntimeStreamEvent(
                    session_id="s2",
                    user_id="u1",
                    run_id="r2",
                    sequence=1,
                    kind="observation",
                    source="runtime",
                    name="runtime.started",
                )
            )

            events = store.list_events(session_id="s1")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "user.message")
        self.assertEqual(events[0].payload["content"], "hello")

    def test_jsonl_event_store_supports_parallel_subagent_writes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = JsonlRuntimeEventStore(Path(tmpdir) / "events.jsonl")

            def record(index: int) -> None:
                store.record(
                    RuntimeStreamEvent(
                        session_id=f"child-{index}",
                        user_id="u1",
                        run_id=f"run-{index}",
                        sequence=1,
                        kind="observation",
                        source="runtime",
                        name="runtime.completed",
                    )
                )

            with ThreadPoolExecutor(max_workers=3) as executor:
                list(executor.map(record, range(30)))

            events = store.list_events()

        self.assertEqual(len(events), 30)
        self.assertEqual(len({event.run_id for event in events}), 30)


if __name__ == "__main__":
    unittest.main()
