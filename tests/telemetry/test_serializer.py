import json
import unittest

from navi_agent.telemetry import ModelCallTrace, RuntimeTrace, ToolExecutionTrace, TraceSerializer


class TraceSerializerTests(unittest.TestCase):
    def test_to_dict_includes_schema_version(self) -> None:
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            system_prompt="system",
            final_response="done",
            status="success",
            agent_role="subagent",
            parent_session_id="parent-1",
            injected_skill_names=["readme-summary"],
            error_category="retryable",
            error_type="RateLimitError",
            error_message="rate limit",
            retryable=True,
            http_status=429,
            error_source="model",
            attempt_count=2,
            model_calls=[
                ModelCallTrace(
                    iteration=1,
                    response_content="done",
                    provider="openai-compatible",
                    model="deepseek-v4-pro",
                    input_tokens=100,
                    output_tokens=20,
                    cost_usd=0.001,
                )
            ],
            tool_executions=[
                ToolExecutionTrace(
                    iteration=1,
                    tool_call_id="tc1",
                    tool_name="echo",
                    status="success",
                    content="pong",
                    error_category="fatal",
                    error_type="ValueError",
                    error_message="bad input",
                    retryable=False,
                    http_status=400,
                )
            ],
        )

        payload = TraceSerializer.to_dict(trace)

        self.assertEqual(payload["schema_version"], "trace.v3")
        self.assertEqual(payload["agent_role"], "subagent")
        self.assertEqual(payload["parent_session_id"], "parent-1")
        self.assertIn("trace_id", payload)
        self.assertEqual(payload["model_calls"][0]["response_content"], "done")
        self.assertEqual(payload["model_calls"][0]["model"], "deepseek-v4-pro")
        self.assertEqual(payload["model_calls"][0]["input_tokens"], 100)
        self.assertEqual(payload["tool_executions"][0]["tool_name"], "echo")
        self.assertEqual(payload["injected_skill_names"], ["readme-summary"])
        self.assertEqual(payload["error_category"], "retryable")
        self.assertEqual(payload["http_status"], 429)
        self.assertEqual(payload["error_source"], "model")
        self.assertEqual(payload["tool_executions"][0]["error_type"], "ValueError")

    def test_to_json_round_trips(self) -> None:
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="done",
            status="success",
        )

        payload = json.loads(TraceSerializer.to_json(trace))

        self.assertEqual(payload["session_id"], "s1")
        self.assertEqual(payload["schema_version"], "trace.v3")

    def test_traces_to_json_lines_exports_multiple_traces(self) -> None:
        traces = [
            RuntimeTrace(session_id="s1", user_id="u1", user_message="a", final_response="ok", status="success"),
            RuntimeTrace(session_id="s2", user_id="u2", user_message="b", final_response="bad", status="failed"),
        ]

        payload = TraceSerializer.traces_to_json_lines(traces)

        lines = payload.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["session_id"], "s2")


if __name__ == "__main__":
    unittest.main()
