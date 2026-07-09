import unittest

from navi_agent.telemetry import LangfuseTraceExporter, ModelCallTrace, RuntimeTrace, ToolExecutionTrace


class FakeLangfuseObservation:
    def __init__(self) -> None:
        self.observations = []
        self.events = []
        self.end_count = 0
        self.trace_id = "trace-1"
        self.id = "obs-1"

    def start_observation(self, **kwargs):
        child = FakeLangfuseObservation()
        child.trace_id = self.trace_id
        child.id = f"child-{len(self.observations) + 1}"
        self.observations.append({"kwargs": kwargs, "child": child})
        return child

    def create_event(self, **kwargs) -> None:
        self.events.append(kwargs)

    def end(self, **kwargs) -> None:
        self.end_count += 1


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.trace_calls = []
        self.traces = []
        self.flush_count = 0

    def start_observation(self, **kwargs) -> FakeLangfuseObservation:
        self.trace_calls.append(kwargs)
        trace = FakeLangfuseObservation()
        trace.trace_id = kwargs["trace_context"]["trace_id"]
        self.traces.append(trace)
        return trace

    def flush(self) -> None:
        self.flush_count += 1


class LangfuseTraceExporterTests(unittest.TestCase):
    def test_export_trace_maps_runtime_trace_to_langfuse(self) -> None:
        client = FakeLangfuseClient()
        exporter = LangfuseTraceExporter(client=client)
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            system_prompt="system",
            final_response="done",
            status="success",
            trace_id="trace-1",
            tool_names=["echo"],
            model_calls=[
                ModelCallTrace(
                    iteration=1,
                    response_content="done",
                    tool_call_names=["echo"],
                    started_at="2026-06-10T10:00:00.000+00:00",
                    completed_at="2026-06-10T10:00:00.010+00:00",
                    duration_ms=10,
                )
            ],
            tool_executions=[
                ToolExecutionTrace(
                    iteration=1,
                    tool_call_id="tc1",
                    tool_name="echo",
                    status="success",
                    arguments={"value": "ping"},
                    content="pong",
                    approval_required=True,
                    started_at="2026-06-10T10:00:00.020+00:00",
                    completed_at="2026-06-10T10:00:00.025+00:00",
                    duration_ms=5,
                )
            ],
            total_iterations=1,
            approval_count=1,
            error_count=0,
            error_category="retryable",
            error_type="RateLimitError",
            error_message="rate limit",
            retryable=True,
            http_status=429,
            attempt_count=2,
            started_at="2026-06-10T10:00:00.000+00:00",
            completed_at="2026-06-10T10:00:00.030+00:00",
            duration_ms=30,
        )

        exporter.export_trace(trace)

        self.assertEqual(client.trace_calls[0]["trace_context"]["trace_id"], "trace-1")
        self.assertEqual(client.trace_calls[0]["as_type"], "agent")
        self.assertEqual(client.trace_calls[0]["metadata"]["approval_count"], 1)
        self.assertEqual(client.trace_calls[0]["metadata"]["error_category"], "retryable")
        self.assertEqual(client.trace_calls[0]["metadata"]["http_status"], 429)
        self.assertEqual(client.trace_calls[0]["metadata"]["duration_ms"], 30)
        self.assertEqual(client.traces[0].observations[0]["kwargs"]["name"], "model.iteration.1")
        self.assertEqual(client.traces[0].observations[0]["kwargs"]["metadata"]["duration_ms"], 10)
        self.assertEqual(client.traces[0].observations[0]["kwargs"]["as_type"], "generation")
        self.assertEqual(client.traces[0].observations[1]["kwargs"]["name"], "tool.echo")
        self.assertEqual(client.traces[0].observations[1]["kwargs"]["metadata"]["duration_ms"], 5)
        self.assertIsNone(client.traces[0].observations[1]["kwargs"]["metadata"]["error_type"])
        self.assertEqual(client.traces[0].observations[1]["kwargs"]["as_type"], "tool")
        self.assertEqual(client.traces[0].events[0]["name"], "approval.echo")
        self.assertEqual(client.traces[0].end_count, 1)
        self.assertEqual(client.flush_count, 1)


if __name__ == "__main__":
    unittest.main()
