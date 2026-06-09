import unittest

from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import InMemoryTraceStore, RuntimeTrace, TraceReplayService


class FakeRuntime:
    def __init__(self) -> None:
        self.calls = []

    def run_conversation(self, session_id, user_id, user_message, system_prompt=None):
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "user_message": user_message,
                "system_prompt": system_prompt,
            }
        )
        return RuntimeResult(
            session_id=session_id,
            status="success",
            final_response="done",
        )


class TraceReplayServiceTests(unittest.TestCase):
    def test_replay_trace_reuses_trace_inputs(self) -> None:
        runtime = FakeRuntime()
        store = InMemoryTraceStore()
        service = TraceReplayService(runtime=runtime, trace_store=store)
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            system_prompt="system",
            final_response="done",
            status="success",
        )

        result = service.replay_trace(trace)

        self.assertEqual(result.source_trace.session_id, "s1")
        self.assertEqual(runtime.calls[0]["user_message"], "hello")
        self.assertEqual(runtime.calls[0]["system_prompt"], "system")
        self.assertTrue(result.replay_session_id.startswith("s1:replay:"))

    def test_replay_latest_uses_store_lookup(self) -> None:
        runtime = FakeRuntime()
        store = InMemoryTraceStore()
        store.record(
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="latest",
                final_response="done",
                status="success",
            )
        )
        service = TraceReplayService(runtime=runtime, trace_store=store)

        result = service.replay_latest(user_id="u1")

        self.assertEqual(result.source_trace.user_message, "latest")
        self.assertEqual(runtime.calls[0]["user_id"], "u1")

    def test_replay_latest_raises_when_no_trace_exists(self) -> None:
        service = TraceReplayService(runtime=FakeRuntime(), trace_store=InMemoryTraceStore())

        with self.assertRaises(ValueError):
            service.replay_latest()


if __name__ == "__main__":
    unittest.main()
