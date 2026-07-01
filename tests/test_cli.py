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
        self.saved_eval_cases = []
        self.applied_candidate = None

    def handle(self, request):
        self.calls.append(request)
        return RuntimeResult(
            session_id=request.session_id or "generated",
            status="success",
            final_response="done",
        )

    def add_candidate(self, candidate) -> None:
        self.saved_candidates.append(candidate)

    def add_eval_case(self, eval_case) -> None:
        self.saved_eval_cases.append(eval_case)

    def list_candidates(self, limit=10, status=None):
        return list(reversed(self.saved_candidates[-limit:]))

    def list_eval_cases(self, limit=10):
        return list(reversed(self.saved_eval_cases[-limit:]))

    def get_candidate(self, candidate_id):
        for candidate in self.saved_candidates:
            if getattr(candidate, "candidate_id", None) == candidate_id:
                return candidate
        return None

    def update_candidate_status(self, candidate_id, status, review_note=None):
        for candidate in self.saved_candidates:
            if getattr(candidate, "candidate_id", None) == candidate_id:
                candidate.status = status
                candidate.review_note = review_note
                return candidate
        return None

    def apply_candidate(self, candidate_id, review_note=None):
        candidate = self.update_candidate_status(candidate_id, "applied", review_note=review_note)
        if candidate is not None:
            self.applied_candidate = candidate
        return candidate


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

    def test_build_parser_parses_banner_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--banner"])

        self.assertTrue(args.banner)

    def test_build_parser_parses_doctor_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--doctor"])

        self.assertTrue(args.doctor)
        self.assertIsNone(args.message)

    def test_build_parser_parses_gateway_flags(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "--gateway",
                "weixin",
                "--gateway-pairings",
                "weixin",
                "--approve-gateway-pairing",
                "123456",
            ]
        )

        self.assertEqual(args.gateway, "weixin")
        self.assertEqual(args.gateway_pairings, "weixin")
        self.assertEqual(args.approve_gateway_pairing, "123456")

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
        args = parser.parse_args(["--evolution-run", "prototype-baseline"])
        self.assertEqual(args.evolution_run, "prototype-baseline")
        args = parser.parse_args(["--confirm-eval-case"])
        self.assertTrue(args.confirm_eval_case)
        args = parser.parse_args(["--evolution-status"])
        self.assertTrue(args.evolution_status)
        args = parser.parse_args(["--curator-status"])
        self.assertTrue(args.curator_status)
        args = parser.parse_args(["--curator-run"])
        self.assertTrue(args.curator_run)
        args = parser.parse_args(["--curator-run", "--dry-run"])
        self.assertTrue(args.curator_run)
        self.assertTrue(args.dry_run)
        args = parser.parse_args(["--candidate-id", "c1", "--accept-candidate"])
        self.assertEqual(args.candidate_id, "c1")
        self.assertTrue(args.accept_candidate)
        args = parser.parse_args(["--candidate-id", "c1", "--apply-candidate-run"])
        self.assertEqual(args.candidate_id, "c1")
        self.assertTrue(args.apply_candidate_run)

    def test_build_parser_parses_evolution_listing_flags(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--list-candidates"])
        self.assertTrue(args.list_candidates)
        self.assertEqual(args.candidate_status, "all")
        args = parser.parse_args(["--candidate-status", "pending", "--list-candidates"])
        self.assertEqual(args.candidate_status, "pending")
        args = parser.parse_args(["--candidate-status", "verified", "--list-candidates"])
        self.assertEqual(args.candidate_status, "verified")
        args = parser.parse_args(["--candidate-status", "superseded", "--list-candidates"])
        self.assertEqual(args.candidate_status, "superseded")
        args = parser.parse_args(["--list-eval-cases"])
        self.assertTrue(args.list_eval_cases)
        args = parser.parse_args(["--prompt-overlay-status"])
        self.assertTrue(args.prompt_overlay_status)
        args = parser.parse_args(["--show-prompt-overlay"])
        self.assertTrue(args.show_prompt_overlay)
        args = parser.parse_args(["--list-prompt-overlay-entries"])
        self.assertTrue(args.list_prompt_overlay_entries)
        args = parser.parse_args(["--list-prompt-overlay-snapshots"])
        self.assertTrue(args.list_prompt_overlay_snapshots)
        args = parser.parse_args(["--rollback-prompt-overlay", "snapshot-1"])
        self.assertEqual(args.rollback_prompt_overlay, "snapshot-1")
        args = parser.parse_args(["--review-loop"])
        self.assertTrue(args.review_loop)
        args = parser.parse_args(["--candidate-triage"])
        self.assertTrue(args.candidate_triage)
        args = parser.parse_args(["--candidate-queue"])
        self.assertTrue(args.candidate_queue)
        args = parser.parse_args(["--candidate-work-items"])
        self.assertTrue(args.candidate_work_items)
        args = parser.parse_args(["--candidate-id", "c1", "--supersede-candidate"])
        self.assertTrue(args.supersede_candidate)
        args = parser.parse_args(["--candidate-id", "c1", "--archive-candidate"])
        self.assertTrue(args.archive_candidate)

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

    def test_main_requires_weixin_token_for_gateway_mode(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.load_config", return_value={}):
            with patch("sys.argv", ["navi-agent", "--gateway", "weixin"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("weixin token is required", stdout.getvalue())

    def test_main_runs_weixin_ilink_mode(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        config = {
            "gateway": {
                "weixin": {
                    "mode": "ilink",
                    "token": "token",
                    "account_id": "account-1",
                    "base_url": "http://127.0.0.1:9001",
                }
            }
        }

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.load_config", return_value=config):
                with patch("navi_agent.cli.ILinkGateway") as gateway_cls:
                    with patch("sys.argv", ["navi-agent", "--gateway", "weixin"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("weixin_ilink_polling: account_id=account-1", stdout.getvalue())
        gateway_cls.return_value.run_forever.assert_called_once_with()

    def test_main_requires_account_id_for_weixin_ilink_mode(self) -> None:
        stdout = io.StringIO()

        with patch(
            "navi_agent.cli.load_config",
            return_value={"gateway": {"weixin": {"mode": "ilink", "token": "token"}}},
        ):
            with patch(
                "sys.argv",
                ["navi-agent", "--gateway", "weixin"],
            ):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("weixin account_id is required", stdout.getvalue())

    def test_main_lists_weixin_pairings(self) -> None:
        stdout = io.StringIO()
        fake_store = type(
            "Store",
            (),
            {
                "list_pending": lambda self: [
                    type("Request", (), {"code": "123456", "user_id": "user-1", "created_at": "now"})()
                ],
                "list_approved": lambda self: ["user-2"],
            },
        )()

        with patch("navi_agent.cli.WeixinPairingStore", return_value=fake_store):
            with patch("sys.argv", ["navi-agent", "--gateway-pairings", "weixin"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("pending_weixin_pairings: 1", stdout.getvalue())
        self.assertIn("123456: user-1", stdout.getvalue())
        self.assertIn("approved_weixin_users: 1", stdout.getvalue())

    def test_main_approves_weixin_pairing(self) -> None:
        stdout = io.StringIO()
        fake_store = type("Store", (), {"approve": lambda self, code: "user-1"})()

        with patch("navi_agent.cli.WeixinPairingStore", return_value=fake_store):
            with patch("sys.argv", ["navi-agent", "--approve-gateway-pairing", "123456"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("approved_weixin_user: user-1", stdout.getvalue())

    def test_main_prints_banner(self) -> None:
        stdout = io.StringIO()

        with patch("sys.argv", ["navi-agent", "--banner"]):
            with redirect_stdout(stdout):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("powered by xushun", stdout.getvalue())
        self.assertIn("███╗   ██╗", stdout.getvalue())

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
        fake_app.list_candidates = lambda limit=50: [
            type("Candidate", (), {"candidate_id": "c1", "status": "pending", "target": "prompt", "summary": "Review prompt"})()
        ]
        fake_app.list_eval_cases = lambda limit=50: [
            type(
                "EvalCase",
                (),
                {
                    "workflow_name": "prototype-baseline",
                    "status": "regressed",
                    "source_average_score": 1.0,
                    "replay_average_score": 0.9,
                    "score_delta": -0.1,
                },
            )()
        ]

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
                "eval_case": type(
                    "EvalCase",
                    (),
                    {
                        "workflow_name": "prototype-baseline",
                        "status": "regressed",
                        "source_average_score": 1.0,
                        "replay_average_score": 0.9,
                        "score_delta": -0.1,
                    },
                )(),
                "candidate": type(
                    "Candidate",
                    (),
                    {
                        "candidate_id": "c1",
                        "status": "pending",
                        "target": "prompt",
                        "summary": "Review workflow regression",
                    },
                )(),
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
                        with patch("navi_agent.cli.EvolutionReportWriter") as report_writer_cls:
                            with patch("sys.argv", ["navi-agent", "--compare-workflow", "prototype-baseline"]):
                                with redirect_stdout(stdout):
                                    report_writer_cls.return_value.write_workflow_comparison_report.return_value = "/tmp/report"
                                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("workflow: prototype-baseline", stdout.getvalue())
        self.assertIn("source_session_id: wf-1", stdout.getvalue())
        self.assertIn("workflow_status: regressed", stdout.getvalue())
        self.assertIn("report_path: /tmp/report", stdout.getvalue())
        self.assertIn("candidate_target: prompt", stdout.getvalue())
        self.assertIn("replay_trace_id: trace-2", stdout.getvalue())
        self.assertEqual(len(fake_app.saved_eval_cases), 1)
        self.assertEqual(len(fake_app.saved_candidates), 1)
        run_smoke_workflow_mock.assert_called_once()
        replay_mock.assert_called_once()
        compare_mock.assert_called_once()

    def test_main_runs_compare_workflow_with_confirmation(self) -> None:
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
                "eval_case": type(
                    "EvalCase",
                    (),
                    {
                        "workflow_name": "prototype-baseline",
                        "status": "regressed",
                        "source_average_score": 1.0,
                        "replay_average_score": 0.9,
                        "score_delta": -0.1,
                    },
                )(),
                "candidate": None,
                "step_comparisons": [],
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.run_smoke_workflow", return_value=workflow_result):
                with patch("navi_agent.cli.replay_smoke_workflow", return_value=workflow_result):
                    with patch("navi_agent.cli.compare_smoke_workflow_results", return_value=comparison):
                        with patch("navi_agent.cli.EvolutionReportWriter") as report_writer_cls:
                            report_writer_cls.return_value.write_workflow_comparison_report.return_value = "/tmp/report"
                            with patch("builtins.input", return_value="y") as input_mock:
                                with patch(
                                    "sys.argv",
                                    ["navi-agent", "--compare-workflow", "prototype-baseline", "--confirm-eval-case"],
                                ):
                                    with redirect_stdout(stdout):
                                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("eval case candidate:", stdout.getvalue())
        self.assertIn("eval_case_saved: yes", stdout.getvalue())
        self.assertEqual(len(fake_app.saved_eval_cases), 1)
        input_mock.assert_called_once()

    def test_main_skips_eval_case_when_confirmation_rejected(self) -> None:
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
                "eval_case": type(
                    "EvalCase",
                    (),
                    {
                        "workflow_name": "prototype-baseline",
                        "status": "regressed",
                        "source_average_score": 1.0,
                        "replay_average_score": 0.9,
                        "score_delta": -0.1,
                    },
                )(),
                "candidate": None,
                "step_comparisons": [],
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.run_smoke_workflow", return_value=workflow_result):
                with patch("navi_agent.cli.replay_smoke_workflow", return_value=workflow_result):
                    with patch("navi_agent.cli.compare_smoke_workflow_results", return_value=comparison):
                        with patch("navi_agent.cli.EvolutionReportWriter") as report_writer_cls:
                            report_writer_cls.return_value.write_workflow_comparison_report.return_value = "/tmp/report"
                            with patch("builtins.input", return_value="n"):
                                with patch(
                                    "sys.argv",
                                    ["navi-agent", "--compare-workflow", "prototype-baseline", "--confirm-eval-case"],
                                ):
                                    with redirect_stdout(stdout):
                                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("eval case candidate:", stdout.getvalue())
        self.assertIn("eval_case_saved: no", stdout.getvalue())
        self.assertEqual(len(fake_app.saved_eval_cases), 0)

    def test_main_runs_apply_candidate_workflow(self) -> None:
        first_app = FakeApp()
        rerun_app = FakeApp()
        stdout = io.StringIO()

        candidate = type(
            "Candidate",
            (),
            {
                "candidate_id": "c1",
                "status": "pending",
                "target": "prompt",
                "summary": "Review workflow regression",
                "review_note": None,
                "metadata": {"workflow_name": "prototype-baseline"},
            },
        )()
        first_app.saved_candidates.append(candidate)
        rerun_app.saved_candidates = first_app.saved_candidates
        rerun_app.saved_eval_cases = first_app.saved_eval_cases

        source_workflow_result = type(
            "WorkflowResult",
            (),
            {
                "workflow": type("Workflow", (), {"name": "prototype-baseline"})(),
                "session_id": "wf-1",
            },
        )()
        replay_workflow_result = type(
            "WorkflowResult",
            (),
            {
                "workflow": type("Workflow", (), {"name": "prototype-baseline"})(),
                "session_id": "wf-1:candidate:c1",
            },
        )()
        comparison = type(
            "WorkflowComparison",
            (),
            {
                "workflow_name": "prototype-baseline",
                "source_session_id": "wf-1",
                "replay_session_id": "wf-1:candidate:c1",
                "source_average_score": 1.0,
                "replay_average_score": 1.05,
                "score_delta": 0.05,
                "eval_case": type(
                    "EvalCase",
                    (),
                    {
                        "workflow_name": "prototype-baseline",
                        "status": "improved",
                        "source_average_score": 1.0,
                        "replay_average_score": 1.05,
                        "score_delta": 0.05,
                    },
                )(),
                "candidate": None,
                "step_comparisons": [],
            },
        )()

        with patch("navi_agent.cli.build_application", side_effect=[first_app, rerun_app]):
            with patch(
                "navi_agent.cli.run_smoke_workflow",
                side_effect=[source_workflow_result, replay_workflow_result],
            ) as run_smoke_workflow_mock:
                with patch("navi_agent.cli.replay_smoke_workflow"):
                    with patch("navi_agent.cli.compare_smoke_workflow_results", return_value=comparison):
                        with patch("navi_agent.cli.EvolutionReportWriter") as report_writer_cls:
                            with patch("sys.argv", ["navi-agent", "--candidate-id", "c1", "--apply-candidate-run"]):
                                with redirect_stdout(stdout):
                                    report_writer_cls.return_value.write_workflow_comparison_report.return_value = "/tmp/report"
                                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(first_app.applied_candidate, candidate)
        self.assertEqual(candidate.status, "verified")
        self.assertIn("candidate_id: c1", stdout.getvalue())
        self.assertIn("candidate_status: verified", stdout.getvalue())
        self.assertIn("workflow: prototype-baseline", stdout.getvalue())
        self.assertIn("candidate_outcome: improved", stdout.getvalue())
        self.assertIn("candidate_report_path: /tmp/report", stdout.getvalue())
        self.assertEqual(run_smoke_workflow_mock.call_count, 2)

    def test_main_runs_evolution_status(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=50, status=None: [
            type("Candidate", (), {"candidate_id": "c1", "status": "pending", "target": "prompt", "summary": "Review prompt"})()
        ]
        fake_app.list_eval_cases = lambda limit=50: [
            type(
                "EvalCase",
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

        latest_report = type(
            "Report",
            (),
            {
                "report_path": "/tmp/evolution-report",
                "workflow_name": "prototype-baseline",
                "status": "regressed",
                "score_delta": -0.2,
                "candidate_target": "prompt",
                "candidate_status": "pending",
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.EvolutionReportStore") as report_store_cls:
                report_store_cls.return_value.get_latest.return_value = latest_report
                with patch("sys.argv", ["navi-agent", "--evolution-status"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("active_candidate_count: 1", stdout.getvalue())
        self.assertIn("verified_candidate_count: 0", stdout.getvalue())
        self.assertIn("no_improvement_candidate_count: 0", stdout.getvalue())
        self.assertIn("regressed_after_apply_candidate_count: 0", stdout.getvalue())
        self.assertIn("superseded_candidate_count: 0", stdout.getvalue())
        self.assertIn("archived_candidate_count: 0", stdout.getvalue())
        self.assertIn("latest_report: /tmp/evolution-report", stdout.getvalue())
        self.assertIn("latest_workflow: prototype-baseline", stdout.getvalue())
        self.assertIn("latest_candidate_target: prompt", stdout.getvalue())
        self.assertIn("latest_candidate_status: pending", stdout.getvalue())
        self.assertIn("recommendation:", stdout.getvalue())

    def test_main_runs_curator_status(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=50, status=None: []
        fake_app.list_eval_cases = lambda limit=50: []
        stdout = io.StringIO()

        latest_report = type(
            "Report",
            (),
            {
                "report_path": "/tmp/evolution-report",
                "workflow_name": "prototype-baseline",
                "status": "improved",
                "score_delta": 0.2,
                "candidate_target": "prompt",
                "candidate_status": "verified",
            },
        )()
        summary = type(
            "ReviewSummary",
            (),
            {
                "candidate_count": 2,
                "active_candidate_count": 1,
                "pending_candidate_count": 1,
                "accepted_candidate_count": 0,
                "rejected_candidate_count": 0,
                "applied_candidate_count": 0,
                "verified_candidate_count": 1,
                "no_improvement_candidate_count": 0,
                "regressed_after_apply_candidate_count": 0,
                "superseded_candidate_count": 1,
                "archived_candidate_count": 0,
                "eval_case_count": 3,
                "regressed_count": 1,
                "improved_count": 1,
                "unchanged_count": 1,
                "pending_targets": [("prompt", 1)],
                "top_candidate_targets": [("prompt", 2)],
                "top_regressed_workflows": [("prototype-baseline", 1)],
                "pending_queue": [
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c1",
                            "target": "prompt",
                            "summary": "Review prompt",
                            "metadata": {
                                "workflow_name": "prototype-baseline",
                                "task_name": "runtime-trace-check",
                            },
                        },
                    )()
                ],
                "recommendation": "Promote verified prompt changes into the baseline before expanding the workflow set.",
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.EvolutionReportStore") as report_store_cls:
                report_store_cls.return_value.get_latest.return_value = latest_report
                with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                    review_service_cls.return_value.summarize.return_value = summary
                    with patch("sys.argv", ["navi-agent", "--curator-status"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("active_candidate_count: 1", stdout.getvalue())
        self.assertIn("pending_targets:", stdout.getvalue())
        self.assertIn("top_regressed_workflows:", stdout.getvalue())
        self.assertIn("top_pending_queue:", stdout.getvalue())
        self.assertIn("latest_candidate_status: verified", stdout.getvalue())

    def test_main_runs_curator_run_with_top_prompt_candidate(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        summary = type(
            "ReviewSummary",
            (),
            {
                "pending_queue": [
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c-tool",
                            "target": "tooling",
                            "metadata": {
                                "workflow_name": "prototype-baseline",
                                "task_name": "workspace-search",
                            },
                        },
                    )(),
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c-prompt",
                            "target": "prompt",
                            "metadata": {
                                "workflow_name": "prototype-baseline",
                                "task_name": "runtime-trace-check",
                                "workflow_status": "regressed",
                                "workflow_score_delta": -0.2,
                                "step_score_delta": -0.1,
                            },
                        },
                    )(),
                ]
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("navi_agent.cli._run_candidate_apply_workflow", return_value=0) as run_apply_mock:
                    with patch("sys.argv", ["navi-agent", "--curator-run"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("curator_candidate_id: c-prompt", stdout.getvalue())
        self.assertIn("curator_target: prompt", stdout.getvalue())
        self.assertIn("curator_workflow: prototype-baseline", stdout.getvalue())
        self.assertIn(
            "curator_selection_reason: prompt candidate prioritized by workflow_status=regressed, workflow_score_delta=-0.2, step_score_delta=-0.1",
            stdout.getvalue(),
        )
        run_apply_mock.assert_called_once()
        self.assertEqual(run_apply_mock.call_args.kwargs["candidate_id"], "c-prompt")

    def test_main_runs_curator_run_dry_run(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        summary = type(
            "ReviewSummary",
            (),
            {
                "pending_queue": [
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c-prompt",
                            "target": "prompt",
                            "metadata": {
                                "workflow_name": "prototype-baseline",
                                "task_name": "runtime-trace-check",
                                "workflow_status": "regressed",
                                "workflow_score_delta": -0.2,
                                "step_score_delta": -0.1,
                            },
                        },
                    )()
                ]
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("navi_agent.cli._run_candidate_apply_workflow", return_value=0) as run_apply_mock:
                    with patch("sys.argv", ["navi-agent", "--curator-run", "--dry-run"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("curator_candidate_id: c-prompt", stdout.getvalue())
        self.assertIn(
            "curator_selection_reason: prompt candidate prioritized by workflow_status=regressed, workflow_score_delta=-0.2, step_score_delta=-0.1",
            stdout.getvalue(),
        )
        self.assertIn("curator_dry_run: yes", stdout.getvalue())
        self.assertIn("curator_action: apply-candidate-run", stdout.getvalue())
        run_apply_mock.assert_not_called()

    def test_main_runs_curator_run_prefers_worse_regressed_prompt_candidate(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        summary = type(
            "ReviewSummary",
            (),
            {
                "pending_queue": [
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c-prompt-later",
                            "target": "prompt",
                            "metadata": {
                                "workflow_name": "prototype-baseline",
                                "task_name": "workspace-search",
                                "workflow_status": "regressed",
                                "workflow_score_delta": -0.1,
                                "step_score_delta": -0.05,
                            },
                        },
                    )(),
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c-prompt-worse",
                            "target": "prompt",
                            "metadata": {
                                "workflow_name": "prototype-baseline",
                                "task_name": "runtime-trace-check",
                                "workflow_status": "regressed",
                                "workflow_score_delta": -0.3,
                                "step_score_delta": -0.2,
                            },
                        },
                    )(),
                ]
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("navi_agent.cli._run_candidate_apply_workflow", return_value=0) as run_apply_mock:
                    with patch("sys.argv", ["navi-agent", "--curator-run"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("curator_candidate_id: c-prompt-worse", stdout.getvalue())
        self.assertIn(
            "curator_selection_reason: prompt candidate prioritized by workflow_status=regressed, workflow_score_delta=-0.3, step_score_delta=-0.2",
            stdout.getvalue(),
        )
        self.assertEqual(run_apply_mock.call_args.kwargs["candidate_id"], "c-prompt-worse")

    def test_main_runs_curator_run_without_prompt_candidate(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        summary = type("ReviewSummary", (), {"pending_queue": []})()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("sys.argv", ["navi-agent", "--curator-run"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("no applicable prompt candidate found in curator queue", stdout.getvalue())

    def test_main_lists_candidates(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=10, status=None: [
            type(
                "Candidate",
                (),
                {
                    "candidate_id": "c1",
                    "status": "pending",
                    "target": "prompt",
                    "summary": "Review prompt",
                },
            )()
        ]
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--list-candidates"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "c1 [pending] prompt: Review prompt")

    def test_main_updates_candidate_status(self) -> None:
        fake_app = FakeApp()
        candidate = type(
            "Candidate",
            (),
            {
                "candidate_id": "c1",
                "status": "pending",
                "target": "prompt",
                "summary": "Review prompt",
                "review_note": None,
            },
        )()
        fake_app.saved_candidates.append(candidate)
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--candidate-id", "c1", "--accept-candidate"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("candidate_status: accepted", stdout.getvalue())
        self.assertEqual(candidate.status, "accepted")

    def test_main_applies_prompt_candidate(self) -> None:
        fake_app = FakeApp()
        candidate = type(
            "Candidate",
            (),
            {
                "candidate_id": "c1",
                "status": "pending",
                "target": "prompt",
                "summary": "Review prompt",
                "review_note": None,
            },
        )()
        fake_app.saved_candidates.append(candidate)
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--candidate-id", "c1", "--apply-candidate"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("candidate_status: applied", stdout.getvalue())
        self.assertEqual(candidate.status, "applied")

    def test_main_lists_eval_cases(self) -> None:
        fake_app = FakeApp()
        fake_app.list_eval_cases = lambda limit=10: [
            type(
                "EvalCase",
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
            with patch("sys.argv", ["navi-agent", "--list-eval-cases"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("prototype-baseline: regressed", stdout.getvalue())

    def test_main_runs_review_loop(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=50, status=None: [
            type("Candidate", (), {"candidate_id": "c1", "status": "pending", "target": "prompt", "summary": "Review prompt"})()
        ]
        fake_app.list_eval_cases = lambda limit=50: [
            type(
                "EvalCase",
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
                "active_candidate_count": 1,
                "pending_candidate_count": 1,
                "accepted_candidate_count": 0,
                "rejected_candidate_count": 0,
                "applied_candidate_count": 0,
                "verified_candidate_count": 0,
                "no_improvement_candidate_count": 0,
                "regressed_after_apply_candidate_count": 0,
                "superseded_candidate_count": 0,
                "archived_candidate_count": 0,
                "eval_case_count": 1,
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
        self.assertIn("active_candidate_count: 1", stdout.getvalue())
        self.assertIn("pending_candidate_count: 1", stdout.getvalue())
        self.assertIn("verified_candidate_count: 0", stdout.getvalue())
        self.assertIn("top_candidate_targets:", stdout.getvalue())
        self.assertIn("recommendation: Prioritize prompt improvements", stdout.getvalue())

    def test_main_runs_candidate_triage(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        summary = type(
            "ReviewSummary",
            (),
            {
                "candidate_count": 2,
                "pending_candidate_count": 1,
                "pending_targets": [("prompt", 1)],
                "candidates_by_target": {
                    "prompt": [
                        type(
                            "Candidate",
                            (),
                            {
                                "candidate_id": "c1",
                                "status": "pending",
                                "summary": "Review prompt overlay wording",
                            },
                        )()
                    ],
                    "tooling": [
                        type(
                            "Candidate",
                            (),
                            {
                                "candidate_id": "c2",
                                "status": "accepted",
                                "summary": "Tighten file edit tool selection",
                            },
                        )()
                    ],
                },
                "recommendation": "Prioritize prompt improvements for prototype-baseline based on recent regressions.",
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("sys.argv", ["navi-agent", "--candidate-triage"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("pending_targets:", stdout.getvalue())
        self.assertIn("candidate_buckets:", stdout.getvalue())
        self.assertIn("prompt:", stdout.getvalue())
        self.assertIn("- c1 [pending] Review prompt overlay wording", stdout.getvalue())
        self.assertIn("tooling:", stdout.getvalue())

    def test_main_runs_candidate_queue(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        summary = type(
            "ReviewSummary",
            (),
            {
                "pending_candidate_count": 2,
                "pending_queue": [
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c1",
                            "target": "prompt",
                            "summary": "Review workflow regression in runtime-trace-check (prompt)",
                            "metadata": {
                                "workflow_name": "prototype-baseline",
                                "workflow_status": "regressed",
                                "workflow_score_delta": -0.3,
                                "task_name": "runtime-trace-check",
                            },
                        },
                    )(),
                    type(
                        "Candidate",
                        (),
                        {
                            "candidate_id": "c2",
                            "target": "tooling",
                            "summary": "Review stagnant workflow step workspace-search (tooling)",
                            "metadata": {
                                "workflow_name": "product-orientation",
                                "workflow_status": "unchanged",
                                "workflow_score_delta": 0.0,
                                "task_name": "workspace-search",
                            },
                        },
                    )(),
                ],
                "recommendation": "Prioritize prompt improvements for prototype-baseline based on recent regressions.",
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("sys.argv", ["navi-agent", "--candidate-queue"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("pending_candidate_count: 2", stdout.getvalue())
        self.assertIn("candidate_queue:", stdout.getvalue())
        self.assertIn("- c1 [prompt] Review workflow regression in runtime-trace-check (prompt)", stdout.getvalue())
        self.assertIn("workflow=prototype-baseline status=regressed workflow_score_delta=-0.3 step=runtime-trace-check", stdout.getvalue())

    def test_main_runs_candidate_work_items(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        summary = type(
            "ReviewSummary",
            (),
            {
                "pending_candidate_count": 1,
                "pending_work_items": [
                    {
                        "candidate_id": "c1",
                        "target": "prompt",
                        "summary": "Review workflow regression in runtime-trace-check (prompt)",
                        "rationale": "Run completed without a final answer",
                        "workflow_name": "prototype-baseline",
                        "workflow_status": "regressed",
                        "workflow_score_delta": -0.3,
                        "task_name": "runtime-trace-check",
                        "step_score_delta": -0.2,
                        "source_trace_id": "trace-1",
                        "replay_trace_id": "trace-2",
                        "source_session_id": "source-1",
                        "replay_session_id": "replay-1",
                        "signals": ["empty_response", "iterations:4"],
                    }
                ],
                "recommendation": "Prioritize prompt improvements for prototype-baseline based on recent regressions.",
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.ReviewLoopService") as review_service_cls:
                review_service_cls.return_value.summarize.return_value = summary
                with patch("sys.argv", ["navi-agent", "--candidate-work-items"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("candidate_work_items:", stdout.getvalue())
        self.assertIn("- c1 [prompt] Review workflow regression in runtime-trace-check (prompt)", stdout.getvalue())
        self.assertIn("workflow=prototype-baseline status=regressed workflow_score_delta=-0.3", stdout.getvalue())
        self.assertIn("step=runtime-trace-check step_score_delta=-0.2", stdout.getvalue())
        self.assertIn("source_trace_id=trace-1 replay_trace_id=trace-2", stdout.getvalue())
        self.assertIn("signals=empty_response,iterations:4", stdout.getvalue())
        self.assertIn("rationale=Run completed without a final answer", stdout.getvalue())

    def test_main_lists_candidates_by_status(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=10, status=None: [
            type("Candidate", (), {"candidate_id": "c1", "status": "accepted", "target": "prompt", "summary": "Review prompt"})()
        ]
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--candidate-status", "accepted", "--list-candidates"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("c1 [accepted] prompt: Review prompt", stdout.getvalue())

    def test_main_shows_prompt_overlay_status(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.PromptOverlayStore") as overlay_cls:
            overlay_cls.return_value.describe.return_value = {
                "path": "/tmp/prompt-overlay.md",
                "exists": True,
                "candidate_count": 2,
                "candidate_ids": ["c1", "c2"],
                "workflow_names": ["prototype-baseline"],
                "source_session_ids": ["source-1"],
                "replay_session_ids": ["replay-1"],
            }
            with patch("sys.argv", ["navi-agent", "--prompt-overlay-status"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("prompt_overlay_candidate_count: 2", stdout.getvalue())
        self.assertIn("prompt_overlay_candidate_ids:", stdout.getvalue())
        self.assertIn("prompt_overlay_workflow_names:", stdout.getvalue())
        self.assertIn("prompt_overlay_source_session_ids:", stdout.getvalue())
        self.assertIn("prompt_overlay_replay_session_ids:", stdout.getvalue())

    def test_main_shows_prompt_overlay_content(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.PromptOverlayStore") as overlay_cls:
            overlay_cls.return_value.get.return_value = "overlay text"
            with patch("sys.argv", ["navi-agent", "--show-prompt-overlay"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "overlay text")

    def test_main_lists_prompt_overlay_entries(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.PromptOverlayStore") as overlay_cls:
            overlay_cls.return_value.list_entries_by_workflow.return_value = {
                "prototype-baseline": [
                    type(
                        "Entry",
                        (),
                        {
                            "candidate_id": "c1",
                            "status": "applied",
                            "target": "prompt",
                            "summary": "Tighten final answer behavior",
                            "step_name": "runtime-trace-check",
                            "source_session_id": "source-1",
                            "replay_session_id": "replay-1",
                        },
                    )()
                ]
            }
            with patch("sys.argv", ["navi-agent", "--list-prompt-overlay-entries"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("workflow: prototype-baseline", stdout.getvalue())
        self.assertIn("- c1 [applied] prompt: Tighten final answer behavior", stdout.getvalue())
        self.assertIn("step: runtime-trace-check", stdout.getvalue())
        self.assertIn("source_session_id: source-1", stdout.getvalue())
        self.assertIn("replay_session_id: replay-1", stdout.getvalue())

    def test_main_lists_prompt_overlay_snapshots(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.PromptOverlayStore") as overlay_cls:
            overlay_cls.return_value.list_snapshots.return_value = [
                type("Snapshot", (), {"snapshot_id": "snapshot-1", "path": "/tmp/snapshots/snapshot-1.md", "candidate_id": "c1"})(),
                type("Snapshot", (), {"snapshot_id": "snapshot-2", "path": "/tmp/snapshots/snapshot-2.md", "candidate_id": None})(),
            ]
            with patch("sys.argv", ["navi-agent", "--list-prompt-overlay-snapshots"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("snapshot-1: /tmp/snapshots/snapshot-1.md candidate=c1", stdout.getvalue())
        self.assertIn("snapshot-2: /tmp/snapshots/snapshot-2.md", stdout.getvalue())

    def test_main_rolls_back_prompt_overlay_snapshot(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.PromptOverlayStore") as overlay_cls:
            overlay_cls.return_value.rollback.return_value = "rolled content"
            with patch("sys.argv", ["navi-agent", "--rollback-prompt-overlay", "snapshot-1"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("rolled back prompt overlay to snapshot-1", stdout.getvalue())

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
        self.assertIn("powered by xushun", stdout.getvalue())
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
