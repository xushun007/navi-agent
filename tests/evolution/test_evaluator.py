import unittest

from navi_agent.evolution import InMemoryCandidateStore, SimpleEvaluator
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


class SimpleEvaluatorTests(unittest.TestCase):
    def test_evaluate_success_trace(self) -> None:
        evaluator = SimpleEvaluator()
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="done",
            status="success",
            tool_names=["echo"],
        )

        result = evaluator.evaluate(trace)

        self.assertEqual(result.session_id, "s1")
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.metadata["tool_names"], ["echo"])
        self.assertEqual(result.metadata["signals"], [])

    def test_build_candidate_for_failed_evaluation(self) -> None:
        evaluator = SimpleEvaluator()
        result = evaluator.evaluate(
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                final_response="failed",
                status="failed",
                error_count=1,
            )
        )

        candidate = evaluator.build_candidate(result)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.target, "tooling")
        self.assertEqual(candidate.metadata["session_id"], "s1")
        self.assertEqual(
            candidate.metadata["failure_attribution"]["primary_failure"],
            "tool_error",
        )

    def test_evaluate_model_failure_trace(self) -> None:
        evaluator = SimpleEvaluator()
        result = evaluator.evaluate(
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                final_response="模型服务暂时不可用",
                status="failed",
                error_source="model",
                error_category="retryable",
                error_type="RateLimitError",
                retryable=True,
                http_status=429,
            )
        )

        attribution = result.metadata["failure_attribution"]
        self.assertEqual(attribution["primary_failure"], "model_error")
        self.assertEqual(attribution["counts"]["model_error"], 1)
        self.assertEqual(attribution["http_status"], 429)
        self.assertIn("primary_failure:model_error", result.metadata["signals"])
        candidate = evaluator.build_candidate(result)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.target, "runtime")

    def test_evaluate_approval_blocked_trace(self) -> None:
        evaluator = SimpleEvaluator()
        result = evaluator.evaluate(
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                final_response="",
                status="success",
                approval_count=2,
                total_iterations=2,
            )
        )

        self.assertLess(result.score, 1.0)
        self.assertIn("approvals:2", result.metadata["signals"])
        self.assertEqual(
            result.metadata["failure_attribution"]["primary_failure"],
            "approval_blocked",
        )
        candidate = evaluator.build_candidate(result)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.target, "tool_policy")

    def test_store_candidate_writes_to_store(self) -> None:
        evaluator = SimpleEvaluator()
        store = InMemoryCandidateStore()
        candidate = evaluator.build_candidate(
            evaluator.evaluate(
                RuntimeTrace(
                    session_id="s1",
                    user_id="u1",
                    user_message="hello",
                    final_response="failed",
                    status="failed",
                )
            )
        )

        evaluator.store_candidate(store, candidate)

        self.assertEqual(len(store.candidates), 1)

    def test_evaluate_empty_response_trace(self) -> None:
        evaluator = SimpleEvaluator()
        result = evaluator.evaluate(
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                final_response="",
                status="success",
            )
        )

        self.assertLess(result.score, 1.0)
        self.assertIn("empty_response", result.metadata["signals"])
        candidate = evaluator.build_candidate(result)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.target, "prompt")

    def test_evaluate_repeated_tools_and_long_duration(self) -> None:
        evaluator = SimpleEvaluator()
        result = evaluator.evaluate(
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                final_response="done",
                status="success",
                duration_ms=35_000,
                tool_executions=[
                    ToolExecutionTrace(iteration=1, tool_call_id="tc1", tool_name="read_file", status="success"),
                    ToolExecutionTrace(iteration=2, tool_call_id="tc2", tool_name="read_file", status="success"),
                ],
            )
        )

        self.assertLess(result.score, 1.0)
        self.assertIn("duplicate_tools:1", result.metadata["signals"])
        self.assertIn("duration_ms:35000", result.metadata["signals"])
        self.assertEqual(result.metadata["duplicate_tool_count"], 1)
        self.assertEqual(
            result.metadata["failure_attribution"]["primary_failure"],
            "slow_response",
        )
        candidate = evaluator.build_candidate(result)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.target, "tooling")

    def test_build_eval_case_candidate_uses_session_signals(self) -> None:
        evaluator = SimpleEvaluator()
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="",
            status="failed",
            error_count=1,
        )

        candidate = evaluator.build_eval_case_candidate(trace)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.target, "eval_case")
        self.assertEqual(candidate.metadata["trace_id"], trace.trace_id)
        self.assertEqual(candidate.metadata["session_id"], "s1")
        self.assertIn("Review failed session", candidate.summary)


if __name__ == "__main__":
    unittest.main()
