from __future__ import annotations

import unittest

from navi_agent.telemetry import (
    InMemoryRuntimeEventStore,
    RuntimeHealthService,
    RuntimeStreamEvent,
)


class RuntimeHealthServiceTests(unittest.TestCase):
    def test_summarizes_runtime_failures_and_tool_errors(self) -> None:
        store = InMemoryRuntimeEventStore()
        store.record(
            RuntimeStreamEvent(
                session_id="s1",
                user_id="u1",
                run_id="r1",
                sequence=1,
                kind="action",
                source="agent",
                name="tool.call",
                payload={"tool_name": "bash"},
            )
        )
        store.record(
            RuntimeStreamEvent(
                session_id="s1",
                user_id="u1",
                run_id="r1",
                sequence=2,
                kind="observation",
                source="tool",
                name="tool.result",
                payload={
                    "tool_name": "bash",
                    "status": "error",
                    "metadata": {
                        "retryable": True,
                        "http_status": 429,
                        "error_type": "RateLimitError",
                    },
                    "structured_content": {"timed_out": True},
                },
            )
        )
        store.record(
            RuntimeStreamEvent(
                session_id="s1",
                user_id="u1",
                run_id="r1",
                sequence=3,
                kind="observation",
                source="runtime",
                name="runtime.completed",
                payload={"status": "failed"},
            )
        )

        summary = RuntimeHealthService(store).summarize(session_id="s1")

        self.assertEqual(summary.run_count, 1)
        self.assertEqual(summary.event_count, 3)
        self.assertEqual(summary.completed_count, 1)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(summary.tool_call_count, 1)
        self.assertEqual(summary.tool_error_count, 1)
        self.assertEqual(summary.timeout_count, 1)
        self.assertEqual(summary.retryable_error_count, 1)
        self.assertEqual(summary.http_status_counts, {429: 1})
        self.assertEqual(summary.error_type_counts, {"RateLimitError": 1})

    def test_render_outputs_empty_summary(self) -> None:
        text = RuntimeHealthService(InMemoryRuntimeEventStore()).render()

        self.assertIn("runtime_health:", text)
        self.assertIn("session_id: *", text)
        self.assertIn("run_count: 0", text)


if __name__ == "__main__":
    unittest.main()
