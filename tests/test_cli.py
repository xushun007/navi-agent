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

    def list_candidates(self, limit=10, status=None):
        return list(reversed(self.saved_candidates[-limit:]))

    def list_workflow_samples(self, limit=10):
        return list(reversed(self.saved_samples[-limit:]))

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
        args = parser.parse_args(["--evolution-status"])
        self.assertTrue(args.evolution_status)
        args = parser.parse_args(["--candidate-id", "c1", "--accept-candidate"])
        self.assertEqual(args.candidate_id, "c1")
        self.assertTrue(args.accept_candidate)

    def test_build_parser_parses_evolution_listing_flags(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--list-candidates"])
        self.assertTrue(args.list_candidates)
        self.assertEqual(args.candidate_status, "all")
        args = parser.parse_args(["--candidate-status", "pending", "--list-candidates"])
        self.assertEqual(args.candidate_status, "pending")
        args = parser.parse_args(["--list-workflow-samples"])
        self.assertTrue(args.list_workflow_samples)
        args = parser.parse_args(["--prompt-overlay-status"])
        self.assertTrue(args.prompt_overlay_status)
        args = parser.parse_args(["--show-prompt-overlay"])
        self.assertTrue(args.show_prompt_overlay)
        args = parser.parse_args(["--list-prompt-overlay-snapshots"])
        self.assertTrue(args.list_prompt_overlay_snapshots)
        args = parser.parse_args(["--rollback-prompt-overlay", "snapshot-1"])
        self.assertEqual(args.rollback_prompt_overlay, "snapshot-1")
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
        fake_app.list_workflow_samples = lambda limit=50: [
            type(
                "Sample",
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
                "sample": type(
                    "Sample",
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
        self.assertEqual(len(fake_app.saved_samples), 1)
        self.assertEqual(len(fake_app.saved_candidates), 1)
        run_smoke_workflow_mock.assert_called_once()
        replay_mock.assert_called_once()
        compare_mock.assert_called_once()

    def test_main_runs_evolution_status(self) -> None:
        fake_app = FakeApp()
        fake_app.list_candidates = lambda limit=50, status=None: [
            type("Candidate", (), {"candidate_id": "c1", "status": "pending", "target": "prompt", "summary": "Review prompt"})()
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
        self.assertIn("latest_report: /tmp/evolution-report", stdout.getvalue())
        self.assertIn("latest_workflow: prototype-baseline", stdout.getvalue())
        self.assertIn("latest_candidate_target: prompt", stdout.getvalue())
        self.assertIn("latest_candidate_status: pending", stdout.getvalue())
        self.assertIn("recommendation:", stdout.getvalue())

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
        fake_app.list_candidates = lambda limit=50, status=None: [
            type("Candidate", (), {"candidate_id": "c1", "status": "pending", "target": "prompt", "summary": "Review prompt"})()
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
                "pending_candidate_count": 1,
                "accepted_candidate_count": 0,
                "rejected_candidate_count": 0,
                "applied_candidate_count": 0,
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
        self.assertIn("pending_candidate_count: 1", stdout.getvalue())
        self.assertIn("top_candidate_targets:", stdout.getvalue())
        self.assertIn("recommendation: Prioritize prompt improvements", stdout.getvalue())

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
