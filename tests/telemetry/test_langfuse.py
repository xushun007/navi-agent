import unittest

from navi_agent.telemetry import LangfuseTraceExporter, ModelCallTrace, RuntimeTrace, ToolExecutionTrace


class FakeLangfuseTrace:
    def __init__(self) -> None:
        self.generations = []
        self.spans = []
        self.events = []

    def generation(self, **kwargs) -> None:
        self.generations.append(kwargs)

    def span(self, **kwargs) -> None:
        self.spans.append(kwargs)

    def event(self, **kwargs) -> None:
        self.events.append(kwargs)


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.trace_calls = []
        self.traces = []
        self.flush_count = 0

    def trace(self, **kwargs) -> FakeLangfuseTrace:
        self.trace_calls.append(kwargs)
        trace = FakeLangfuseTrace()
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
            tool_names=["echo"],
            model_calls=[
                ModelCallTrace(
                    iteration=1,
                    response_content="done",
                    tool_call_names=["echo"],
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
                )
            ],
            total_iterations=1,
            approval_count=1,
            error_count=0,
        )

        exporter.export_trace(trace)

        self.assertEqual(client.trace_calls[0]["session_id"], "s1")
        self.assertEqual(client.trace_calls[0]["metadata"]["approval_count"], 1)
        self.assertEqual(client.traces[0].generations[0]["name"], "model.iteration.1")
        self.assertEqual(client.traces[0].spans[0]["name"], "tool.echo")
        self.assertEqual(client.traces[0].events[0]["name"], "approval.echo")
        self.assertEqual(client.flush_count, 1)


if __name__ == "__main__":
    unittest.main()
