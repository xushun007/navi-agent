import unittest

from navi_agent.telemetry import CompositeTraceStore, InMemoryTraceStore, RuntimeTrace


class FakeExporter:
    def __init__(self) -> None:
        self.traces = []

    def export_trace(self, trace: RuntimeTrace) -> None:
        self.traces.append(trace)


class CompositeTraceStoreTests(unittest.TestCase):
    def test_record_writes_to_primary_and_exporters(self) -> None:
        primary = InMemoryTraceStore()
        exporter = FakeExporter()
        store = CompositeTraceStore(primary=primary, exporters=[exporter])
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="done",
            status="success",
        )

        store.record(trace)

        self.assertEqual(len(primary.traces), 1)
        self.assertEqual(len(exporter.traces), 1)


if __name__ == "__main__":
    unittest.main()
