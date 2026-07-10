import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from navi_agent.telemetry import JsonlTraceStore, RuntimeTrace


class JsonlTraceStoreTests(unittest.TestCase):
    def test_record_and_list_traces(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(Path(tmpdir) / "traces.jsonl")
            store.record(
                RuntimeTrace(
                    session_id="s1",
                    user_id="u1",
                    user_message="a",
                    final_response="ok",
                    status="success",
                    injected_skill_names=["readme-summary"],
                    completed_at="2026-07-11T10:00:00+00:00",
                )
            )
            store.record(
                RuntimeTrace(
                    session_id="s2",
                    user_id="u2",
                    user_message="b",
                    final_response="bad",
                    status="failed",
                )
            )

            traces = store.list_traces(user_id="u1")

        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].session_id, "s1")
        self.assertEqual(traces[0].injected_skill_names, ["readme-summary"])

    def test_get_latest_trace(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(Path(tmpdir) / "traces.jsonl")
            store.record(
                RuntimeTrace(
                    session_id="s1",
                    user_id="u1",
                    user_message="a",
                    final_response="ok",
                    status="success",
                )
            )
            store.record(
                RuntimeTrace(
                    session_id="s2",
                    user_id="u1",
                    user_message="b",
                    final_response="ok",
                    status="success",
                )
            )

            trace = store.get_latest_trace(user_id="u1")

        self.assertIsNotNone(trace)
        self.assertEqual(trace.session_id, "s2")


if __name__ == "__main__":
    unittest.main()
