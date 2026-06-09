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

    def test_list_traces_supports_filters_and_limit(self) -> None:
        store = InMemoryTraceStore()
        store.record(RuntimeTrace(session_id="s1", user_id="u1", user_message="a", final_response="ok", status="success"))
        store.record(RuntimeTrace(session_id="s2", user_id="u1", user_message="b", final_response="bad", status="failed"))
        store.record(RuntimeTrace(session_id="s3", user_id="u2", user_message="c", final_response="ok", status="success"))

        traces = store.list_traces(user_id="u1", limit=1)

        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].session_id, "s2")

    def test_get_session_traces_returns_all_for_session(self) -> None:
        store = InMemoryTraceStore()
        store.record(RuntimeTrace(session_id="s1", user_id="u1", user_message="a", final_response="ok", status="success"))
        store.record(RuntimeTrace(session_id="s1", user_id="u1", user_message="b", final_response="ok", status="success"))
        store.record(RuntimeTrace(session_id="s2", user_id="u1", user_message="c", final_response="ok", status="success"))

        traces = store.get_session_traces("s1", user_id="u1")

        self.assertEqual(len(traces), 2)
        self.assertEqual([trace.user_message for trace in traces], ["a", "b"])

    def test_get_latest_trace_supports_session_filter(self) -> None:
        store = InMemoryTraceStore()
        store.record(RuntimeTrace(session_id="s1", user_id="u1", user_message="a", final_response="ok", status="success"))
        store.record(RuntimeTrace(session_id="s2", user_id="u1", user_message="b", final_response="ok", status="failed"))

        trace = store.get_latest_trace(session_id="s1")

        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertEqual(trace.session_id, "s1")
        self.assertEqual(trace.user_message, "a")
