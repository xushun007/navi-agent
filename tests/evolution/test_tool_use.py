import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from navi_agent.evolution import (
    ToolUseEvalCase,
    ToolUseEvalCaseStore,
    ToolUseEvalWorkflowService,
    ToolUseEvaluator,
    ToolUseRunStore,
    ToolUseRunSummary,
    ToolUseRunWriter,
    ToolUseWorkflowService,
)
from navi_agent.evolution.tool_use import _build_tool_use_metrics
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


class ToolUseEvalTests(unittest.TestCase):
    def test_store_loads_unified_l0_l1_l2_cases(self) -> None:
        store = ToolUseEvalCaseStore(Path("data/eval/tool_use_seed.jsonl"))

        cases = store.list_cases()

        self.assertGreaterEqual(len(cases), 10)
        self.assertEqual({case.level for case in cases}, {"L0", "L1", "L2"})
        self.assertTrue(all(case.source_inspiration for case in cases))
        self.assertTrue(
            {
                "tooluse_l0_todo_add_001",
                "tooluse_l0_todo_list_pending_001",
                "tooluse_l1_todo_add_in_progress_001",
                "tooluse_l1_todo_list_completed_001",
                "tooluse_l1_code_executor_approval_001",
                "tooluse_l2_memory_preference_state_001",
            }.issubset({case.id for case in cases})
        )

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

        self.assertEqual(summary.count, len(ToolUseEvalCaseStore(Path("data/eval/tool_use_seed.jsonl")).list_cases()))
        self.assertEqual(summary.passed_count, summary.count)
        self.assertEqual(summary.pass_rate, 1.0)
        self.assertEqual(summary.metrics["tool_selection_accuracy"], 1.0)
        self.assertEqual(summary.metrics["required_tool_recall"], 1.0)
        self.assertEqual(summary.metrics["tool_error_count"], 0)
        self.assertIsNotNone(summary.report_path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["count"], summary.count)
        self.assertEqual(latest["metrics"]["tool_selection_accuracy"], 1.0)

    def test_writer_reports_tool_use_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_path = Path(tmpdir) / "tool_use.jsonl"
            report_root = Path(tmpdir) / "reports"
            ToolUseEvalCaseStore(case_path).write_cases([])
            result = ToolUseEvaluator().evaluate(
                ToolUseEvalCase(
                    id="case-1",
                    level="L0",
                    category="tool_use.file_read",
                    prompt="read README",
                    source_inspiration="bfcl",
                    required_tools=["read_file"],
                    forbidden_tools=["bash"],
                ),
                RuntimeTrace(
                    session_id="s1",
                    user_id="u1",
                    user_message="read README",
                    final_response="done",
                    status="success",
                    total_iterations=1,
                    tool_executions=[
                        ToolExecutionTrace(
                            iteration=1,
                            tool_call_id="tc1",
                            tool_name="bash",
                            status="success",
                        )
                    ],
                ),
            )
            metrics = _build_tool_use_metrics([result])
            summary = ToolUseRunSummary(
                count=1,
                passed_count=0,
                failed_count=1,
                pass_rate=0.0,
                results=[result],
                metrics=metrics,
            )

            report_path = ToolUseRunWriter(report_root).write_run_report(
                case_store=ToolUseEvalCaseStore(case_path),
                summary=summary,
            )
            payload = json.loads((report_path / "run.json").read_text(encoding="utf-8"))
            markdown = (report_path / "REPORT.md").read_text(encoding="utf-8")

        self.assertEqual(payload["metrics"]["tool_selection_accuracy"], 0.0)
        self.assertEqual(payload["metrics"]["required_tool_recall"], 0.0)
        self.assertEqual(payload["metrics"]["forbidden_tool_clean_rate"], 0.0)
        self.assertIn("## Metrics", markdown)
        self.assertIn("- tool_selection_accuracy: 0.0", markdown)

    def test_llm_workflow_uses_real_runner_interface(self) -> None:
        class FakeRuntime:
            def __init__(self, *, trace_store, **kwargs) -> None:
                self._trace_store = trace_store
                self.calls = []

            def run_conversation(self, *, session_id, user_id, user_message, system_prompt=None):
                self.calls.append((session_id, user_id, user_message, system_prompt))
                self._trace_store.record(
                    RuntimeTrace(
                        session_id=session_id,
                        user_id=user_id,
                        user_message=user_message,
                        final_response="done",
                        status="success",
                        total_iterations=1,
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
                )
                return type("Result", (), {"session_id": session_id})()

        case = ToolUseEvalCase(
            id="case-llm-1",
            level="L0",
            category="tool_use.file_read",
            prompt="读取 README.md",
            source_inspiration="bfcl",
            required_tools=["read_file"],
            expected_args={"read_file": {"path": "README.md"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            case_path = Path(tmpdir) / "tool_use.jsonl"
            report_root = Path(tmpdir) / "reports"
            ToolUseEvalCaseStore(case_path).write_cases([case])

            with mock.patch("navi_agent.evolution.tool_use.AgentRuntime", FakeRuntime):
                with mock.patch("navi_agent.evolution.tool_use.build_transport", return_value=object()):
                    service = ToolUseEvalWorkflowService(
                        case_store=ToolUseEvalCaseStore(case_path),
                        report_root=report_root,
                        model_settings=type("Settings", (), {"model": "fake", "api_key": "fake"})(),
                        runtime_settings=type("Runtime", (), {"max_iterations": 3})(),
                    )
                    summary = service.run()

        self.assertEqual(summary.count, 1)
        self.assertEqual(summary.passed_count, 1)
        self.assertEqual(summary.pass_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
