import unittest

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import RuntimeTrace


class FakeRuntime:
    def __init__(self) -> None:
        self.calls = []
        self.latest_trace = None
        self.session_traces = []

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

    def get_latest_trace(self, session_id=None, user_id=None):
        return self.latest_trace

    def get_session_traces(self, session_id, user_id=None):
        return self.session_traces


class ApplicationServiceTests(unittest.TestCase):
    def test_handle_uses_existing_session_id(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(runtime=runtime)

        result = service.handle(
            AppRequest(
                session_id="s1",
                user_id="u1",
                message="hello",
            )
        )

        self.assertEqual(result.session_id, "s1")
        self.assertEqual(runtime.calls[0]["session_id"], "s1")

    def test_handle_generates_session_id_when_missing(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(runtime=runtime)

        result = service.handle(AppRequest(user_id="u1", message="hello"))

        self.assertTrue(result.session_id)
        self.assertEqual(runtime.calls[0]["session_id"], result.session_id)

    def test_handle_uses_default_system_prompt(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(
            runtime=runtime,
            default_system_prompt="system",
        )

        service.handle(AppRequest(user_id="u1", message="hello"))

        self.assertEqual(runtime.calls[0]["system_prompt"], "system")

    def test_get_latest_trace_delegates_to_runtime(self) -> None:
        runtime = FakeRuntime()
        runtime.latest_trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="done",
            status="success",
            trace_id="trace-1",
        )
        service = ApplicationService(runtime=runtime)

        trace = service.get_latest_trace(session_id="s1", user_id="u1")

        self.assertEqual(trace.trace_id, "trace-1")

    def test_get_session_traces_delegates_to_runtime(self) -> None:
        runtime = FakeRuntime()
        runtime.session_traces = [
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                final_response="done",
                status="success",
                trace_id="trace-1",
            )
        ]
        service = ApplicationService(runtime=runtime)

        traces = service.get_session_traces("s1", user_id="u1")

        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].trace_id, "trace-1")


if __name__ == "__main__":
    unittest.main()
