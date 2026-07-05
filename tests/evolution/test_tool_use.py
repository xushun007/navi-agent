import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import (
    ToolUseEvalCase,
    ToolUseEvalCaseStore,
    ToolUseEvaluator,
    ToolUseRunStore,
    ToolUseWorkflowService,
)
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


class ToolUseEvalTests(unittest.TestCase):
    def test_store_loads_unified_l0_l1_l2_cases(self) -> None:
        store = ToolUseEvalCaseStore(Path("data/eval/tool_use_seed.jsonl"))

        cases = store.list_cases()

        self.assertGreaterEqual(len(cases), 5)
        self.assertEqual({case.level for case in cases}, {"L0", "L1", "L2"})
        self.assertTrue(all(case.source_inspiration for case in cases))

    def test_store_round_trips_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tool_use.jsonl"
            store = ToolUseEvalCaseStore(path)
            store.write_cases(
                [
                    ToolUseEvalCase(
                        id="case-1",
                        level="L0",
                        category="tool_use.file_read",
                        prompt="read README",
                        source_inspiration="bfcl",
                        required_tools=["read_file"],
                        expected_args={"read_file": {"path": "README.md"}},
                    )
                ]
            )

            loaded = store.list_cases()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].required_tools, ["read_file"])
        self.assertEqual(loaded[0].expected_args["read_file"]["path"], "README.md")

    def test_evaluator_passes_required_tool_and_args(self) -> None:
        case = ToolUseEvalCase(
            id="case-1",
            level="L0",
            category="tool_use.file_read",
            prompt="read README",
            source_inspiration="bfcl",
            required_tools=["read_file"],
            forbidden_tools=["write_file"],
            expected_args={"read_file": {"path": "README.md"}},
        )
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message=case.prompt,
            final_response="README says ...",
            status="success",
            total_iterations=2,
            tool_executions=[
                ToolExecutionTrace(
                    iteration=1,
                    tool_call_id="tc1",
                    tool_name="read_file",
                    status="success",
                    arguments={"path": "README.md"},
                    content="...",
                )
            ],
        )

        result = ToolUseEvaluator().evaluate(case, trace)

        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.metadata["tool_names"], ["read_file"])

    def test_evaluator_fails_missing_forbidden_and_arg_mismatch(self) -> None:
        case = ToolUseEvalCase(
            id="case-1",
            level="L1",
            category="tool_use.patch",
            prompt="patch README",
            source_inspiration="toolbench",
            required_tools=["patch"],
            forbidden_tools=["bash"],
            expected_args={"patch": {"path": "README.md"}},
            max_iterations=2,
        )
        trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message=case.prompt,
            final_response="done",
            status="success",
            total_iterations=3,
            tool_executions=[
                ToolExecutionTrace(
                    iteration=1,
                    tool_call_id="tc1",
                    tool_name="patch",
                    status="success",
                    arguments={"path": "docs.md"},
                    content="patched",
                ),
                ToolExecutionTrace(
                    iteration=2,
                    tool_call_id="tc2",
                    tool_name="bash",
                    status="success",
                    arguments={"command": "cat README.md"},
                    content="...",
                ),
            ],
        )

        result = ToolUseEvaluator().evaluate(case, trace)

        self.assertFalse(result.passed)
        self.assertIn("forbidden_tools:bash", result.metadata["signals"])
        self.assertIn("arg_mismatches:patch", result.metadata["signals"])
        self.assertIn("iterations:3>2", result.metadata["signals"])

    def test_workflow_runs_seed_cases_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir) / "reports"
            service = ToolUseWorkflowService(
                case_store=ToolUseEvalCaseStore(Path("data/eval/tool_use_seed.jsonl")),
                report_root=report_root,
            )

            summary = service.run()
            latest = ToolUseRunStore(report_root).get_latest()

        self.assertEqual(summary.count, 5)
        self.assertEqual(summary.passed_count, 5)
        self.assertEqual(summary.pass_rate, 1.0)
        self.assertIsNotNone(summary.report_path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["count"], 5)


if __name__ == "__main__":
    unittest.main()
