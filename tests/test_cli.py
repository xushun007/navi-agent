import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from navi_agent.cli import _run_interactive, build_parser, main
from navi_agent.runtime import CliApprovalProvider, RuntimeResult


class FakeApp:
    def __init__(self) -> None:
        self.calls = []
        self.saved_candidates = []
        self.saved_samples = []

    def handle(self, request):
        self.calls.append(request)
        return RuntimeResult(
            session_id=request.session_id or "generated",
            status="success",
            final_response="done",
        )

    def add_candidate(self, candidate) -> None:
        self.saved_candidates.append(candidate)

    def add_workflow_sample(self, sample) -> None:
        self.saved_samples.append(sample)


class CliTests(unittest.TestCase):
    def test_build_parser_parses_expected_arguments(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            ["--user-id", "u1", "--session-id", "s1", "--system-prompt", "system", "hello"]
        )

        self.assertEqual(args.user_id, "u1")
        self.assertEqual(args.session_id, "s1")
        self.assertEqual(args.system_prompt, "system")
        self.assertEqual(args.message, "hello")
        self.assertFalse(args.interactive)

    def test_build_parser_parses_interactive_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--interactive"])

        self.assertTrue(args.interactive)
        self.assertIsNone(args.message)

    def test_build_parser_parses_doctor_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--doctor"])

        self.assertTrue(args.doctor)
        self.assertIsNone(args.message)

    def test_build_parser_parses_smoke_flags(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--smoke", "config-check"])

        self.assertEqual(args.smoke, "config-check")
        self.assertFalse(args.list_smoke_tasks)
        self.assertIsNone(args.workflow)

    def test_build_parser_parses_workflow_flags(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--workflow", "prototype-baseline"])

        self.assertEqual(args.workflow, "prototype-baseline")
        self.assertFalse(args.list_smoke_workflows)

    def test_build_parser_parses_compare_workflow_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--compare-workflow", "prototype-baseline"])

        self.assertEqual(args.compare_workflow, "prototype-baseline")

    def test_build_parser_parses_evolution_listing_flags(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--list-candidates"])
        self.assertTrue(args.list_candidates)
        args = parser.parse_args(["--list-workflow-samples"])
        self.assertTrue(args.list_workflow_samples)
        args = parser.parse_args(["--review-loop"])
        self.assertTrue(args.review_loop)

    def test_main_builds_application_and_prints_result(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app) as build_application_mock:
            with patch("sys.argv", ["navi-agent", "--user-id", "u1", "hello"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "done")
        build_application_mock.assert_called_once()
        _, kwargs = build_application_mock.call_args
        self.assertEqual(kwargs["default_system_prompt"], None)
        self.assertIsInstance(kwargs["approval_provider"], CliApprovalProvider)
        self.assertEqual(fake_app.calls[0].user_id, "u1")
        self.assertEqual(fake_app.calls[0].message, "hello")

    def test_main_requires_message_without_interactive(self) -> None:
        with patch("sys.argv", ["navi-agent"]):
            with self.assertRaises(SystemExit):
                main()

    def test_main_runs_doctor_mode(self) -> None:
        with patch("navi_agent.cli.run_doctor", return_value=0) as run_doctor_mock:
            with patch("sys.argv", ["navi-agent", "--doctor"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        run_doctor_mock.assert_called_once_with()

    def test_main_lists_smoke_tasks(self) -> None:
        stdout = io.StringIO()

        with patch(
            "navi_agent.cli.list_smoke_tasks",
            return_value=[type("Task", (), {"name": "config-check", "description": "desc"})()],
        ):
            with patch("sys.argv", ["navi-agent", "--list-smoke-tasks"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "config-check: desc")

    def test_main_lists_smoke_workflows(self) -> None:
        stdout = io.StringIO()

        with patch(
            "navi_agent.cli.list_smoke_workflows",
            return_value=[type("Workflow", (), {"name": "prototype-baseline", "description": "desc"})()],
        ):
            with patch("sys.argv", ["navi-agent", "--list-smoke-workflows"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "prototype-baseline: desc")

    def test_main_runs_smoke_task(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch(
                "navi_agent.cli.run_smoke_task",
                return_value=RuntimeResult(session_id="s1", status="success", final_response="done"),
            ) as run_smoke_task_mock:
                with patch("sys.argv", ["navi-agent", "--smoke", "config-check"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "done")
        run_smoke_task_mock.assert_called_once()

    def test_main_runs_smoke_workflow(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        workflow_result = type(
            "WorkflowResult",
            (),
            {
                "workflow": type("Workflow", (), {"name": "prototype-baseline", "steps": ["config-check", "workspace-search"]})(),
                "session_id": "wf-1",
                "steps": [
                    type(
                        "StepResult",
                        (),
                        {
                            "task_name": "config-check",
                            "trace_id": "trace-1",
                            "runtime_result": RuntimeResult(session_id="wf-1", status="success", final_response="first"),
                        },
                    )(),
                    type(
                        "StepResult",
                        (),
                        {
                            "task_name": "workspace-search",
                            "trace_id": "trace-2",
                            "runtime_result": RuntimeResult(session_id="wf-1", status="success", final_response="second"),
                        },
                    )(),
                ],
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch(
                "navi_agent.cli.run_smoke_workflow",
                return_value=workflow_result,
            ) as run_smoke_workflow_mock:
                with patch("sys.argv", ["navi-agent", "--workflow", "prototype-baseline"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("workflow: prototype-baseline", stdout.getvalue())
        self.assertIn("[1] config-check", stdout.getvalue())
        self.assertIn("trace_id: trace-1", stdout.getvalue())
        self.assertIn("second", stdout.getvalue())
        run_smoke_workflow_mock.assert_called_once()

    def test_main_runs_compare_workflow(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        workflow_result = type(
            "WorkflowResult",
            (),
            {
                "workflow": type("Workflow", (), {"name": "prototype-baseline"})(),
                "session_id": "wf-1",
            },
        )()
        comparison = type(
            "WorkflowComparison",
            (),
            {
                "workflow_name": "prototype-baseline",
                "source_session_id": "wf-1",
                "replay_session_id": "wf-1:replay:abcd1234",
                "source_average_score": 1.0,
                "replay_average_score": 0.9,
                "score_delta": -0.1,
                "sample": type("Sample", (), {"status": "regressed"})(),
                "candidate": type("Candidate", (), {"target": "prompt", "summary": "Review workflow regression"})(),
                "step_comparisons": [
                    type(
                        "StepComparison",
                        (),
                        {
                            "task_name": "config-check",
                            "source_step": type("Step", (), {"trace_id": "trace-1"})(),
                            "replay_step": type("Step", (), {"trace_id": "trace-2"})(),
                            "score_delta": -0.1,
                        },
                    )()
                ],
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.run_smoke_workflow", return_value=workflow_result) as run_smoke_workflow_mock:
                with patch("navi_agent.cli.replay_smoke_workflow", return_value=workflow_result) as replay_mock:
                    with patch("navi_agent.cli.compare_smoke_workflow_results", return_value=comparison) as compare_mock:
                        with patch("sys.argv", ["navi-agent", "--compare-workflow", "prototype-baseline"]):
                            with redirect_stdout(stdout):
                                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("workflow: prototype-baseline", stdout.getvalue())
        self.assertIn("source_session_id: wf-1", stdout.getvalue())
        self.assertIn("workflow_status: regressed", stdout.getvalue())
        self.assertIn("candidate_target: prompt", stdout.getvalue())
        self.assertIn("replay_trace_id: trace-2", stdout.getvalue())
        self.assertEqual(len(fake_app.saved_samples), 1)
        self.assertEqual(len(fake_app.saved_candidates), 1)
        run_smoke_workflow_mock.assert_called_once()
        replay_mock.assert_called_once()
        compare_mock.assert_called_once()

    def test_main_lists_candidates(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=10: [
            type("Candidate", (), {"target": "prompt", "summary": "Review prompt"})()
        ]
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--list-candidates"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "prompt: Review prompt")

    def test_main_lists_workflow_samples(self) -> None:
        fake_app = FakeApp()
        fake_app.list_workflow_samples = lambda limit=10: [
            type(
                "Sample",
                (),
                {
                    "workflow_name": "prototype-baseline",
                    "status": "regressed",
                    "source_average_score": 1.0,
                    "replay_average_score": 0.8,
                    "score_delta": -0.2,
                },
            )()
        ]
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--list-workflow-samples"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("prototype-baseline: regressed", stdout.getvalue())

    def test_main_runs_review_loop(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=50: [
            type("Candidate", (), {"target": "prompt", "summary": "Review prompt"})()
        ]
        fake_app.list_workflow_samples = lambda limit=50: [
            type(
                "Sample",
                (),
                {
                    "workflow_name": "prototype-baseline",
                    "status": "regressed",
                    "source_average_score": 1.0,
                    "replay_average_score": 0.8,
                    "score_delta": -0.2,
                },
            )()
        ]
        stdout = io.StringIO()
        summary = type(
            "ReviewSummary",
            (),
            {
                "candidate_count": 1,
                "workflow_sample_count": 1,
                "regressed_count": 1,
                "improved_count": 0,
                "unchanged_count": 0,
                "top_candidate_targets": [("prompt", 1)],
                "top_regressed_workflows": [("prototype-baseline", 1)],
                "recommendation": "Prioritize prompt improvements for prototype-baseline based on recent regressions.",
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("sys.argv", ["navi-agent", "--review-loop"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("candidate_count: 1", stdout.getvalue())
        self.assertIn("top_candidate_targets:", stdout.getvalue())
        self.assertIn("recommendation: Prioritize prompt improvements", stdout.getvalue())

    def test_run_interactive_reuses_session_and_stops_on_exit(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("builtins.input", side_effect=["hello", "again", "exit"]):
            with redirect_stdout(stdout):
                exit_code = _run_interactive(
                    app=fake_app,
                    user_id="u1",
                    session_id="s1",
                    system_prompt="system",
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [(request.session_id, request.message) for request in fake_app.calls],
            [("s1", "hello"), ("s1", "again")],
        )
        self.assertIn("Interactive session: s1", stdout.getvalue())
        self.assertEqual(stdout.getvalue().strip().splitlines()[-2:], ["done", "done"])

    def test_main_runs_interactive_mode_with_first_message(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("builtins.input", side_effect=["quit"]):
                with patch("sys.argv", ["navi-agent", "--interactive", "--session-id", "s1", "hello"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake_app.calls), 1)
        self.assertEqual(fake_app.calls[0].session_id, "s1")
        self.assertEqual(fake_app.calls[0].message, "hello")


if __name__ == "__main__":
    unittest.main()
