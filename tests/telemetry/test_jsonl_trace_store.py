import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from navi_agent.telemetry import JsonlTraceStore, ModelCallTrace, RuntimeTrace, ToolExecutionTrace


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

    def test_restores_nested_trace_objects(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(Path(tmpdir) / "traces.jsonl")
            store.record(
                RuntimeTrace(
                    session_id="s1",
                    user_id="u1",
                    user_message="a",
                    final_response="ok",
                    status="success",
                    model_calls=[
                        ModelCallTrace(iteration=1, response_content="tool call"),
                    ],
                    tool_executions=[
                        ToolExecutionTrace(
                            iteration=1,
                            tool_call_id="tc1",
                            tool_name="read_file",
                            status="success",
                        )
                    ],
                )
            )

            trace = store.get_latest_trace(session_id="s1", user_id="u1")

        self.assertIsNotNone(trace)
        self.assertIsInstance(trace.model_calls[0], ModelCallTrace)
        self.assertIsInstance(trace.tool_executions[0], ToolExecutionTrace)
        self.assertEqual(trace.tool_executions[0].tool_name, "read_file")

    def test_concurrent_records_remain_valid_json_lines(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(Path(tmpdir) / "traces.jsonl")

            def record(index: int) -> None:
                store.record(
                    RuntimeTrace(
                        session_id=f"child-{index}",
                        user_id="u1",
                        user_message="task",
                        final_response="report",
                        status="success",
                    )
                )

            with ThreadPoolExecutor(max_workers=3) as executor:
                list(executor.map(record, range(30)))

            traces = store.list_traces()

        self.assertEqual(len(traces), 30)
        self.assertEqual(len({trace.session_id for trace in traces}), 30)


if __name__ == "__main__":
    unittest.main()
