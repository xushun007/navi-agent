import unittest

from navi_agent.telemetry import InMemoryTraceStore, RuntimeTrace


class TraceStoreTest(unittest.TestCase):
    def test_runtime_trace_data_and_defaults(self) -> None:
        trace = RuntimeTrace(session_id="s1", user_id="u1", user_message="hi", final_response="ok", status="success")
        self.assertEqual(trace.session_id, "s1")
        self.assertEqual(trace.tool_names, [])

    def test_record_and_retrieve(self) -> None:
        store = InMemoryTraceStore()
        trace = RuntimeTrace(session_id="s1", user_id="u1", user_message="hi", final_response="ok", status="success")
        store.record(trace)
        store.record(trace)
        self.assertEqual(len(store.traces), 2)

    def test_store_isolation(self) -> None:
        s1, s2 = InMemoryTraceStore(), InMemoryTraceStore()
        s1.record(RuntimeTrace(session_id="s1", user_id="u1", user_message="hi", final_response="ok", status="success"))
        self.assertEqual(len(s1.traces), 1)
        self.assertEqual(len(s2.traces), 0)
