import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from navi_agent.evolution import (
    EvalSeed,
    EvolutionCandidate,
    SkillCuratorRecord,
    SkillCuratorStatus,
    SkillUsageRecord,
)
from navi_agent.evolution import EvalSeedStore
from navi_agent.cli import _run_interactive, build_parser, main
from navi_agent.runtime import CliApprovalProvider, Message, RuntimeResult, WorkspaceYoloApprovalProvider
from navi_agent.smoke import SmokeCheckResult, SmokeRunSummary


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


class FakeSessionStore:
    def __init__(self, messages):
        self._messages = messages

    def snapshot(self, session):
        return list(self._messages)


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

    def test_build_parser_parses_yolo_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--yolo", "hello"])
        short_args = parser.parse_args(["-y", "hello"])

        self.assertTrue(args.yolo)
        self.assertTrue(short_args.yolo)

    def test_build_parser_parses_banner_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--banner"])

        self.assertTrue(args.banner)

    def test_build_parser_parses_doctor_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--doctor"])

        self.assertTrue(args.doctor)
        self.assertIsNone(args.message)

    def test_build_parser_parses_unified_workflow_run_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--workflow-kind", "healthcheck", "--workflow-phase", "run", "--workflow-name", "agent-healthcheck"])

        self.assertEqual(args.workflow_kind, "healthcheck")
        self.assertEqual(args.workflow_phase, "run")
        self.assertEqual(args.workflow_name, "agent-healthcheck")

        args = parser.parse_args(["--workflow-kind", "tool_use", "--workflow-phase", "run"])
        self.assertEqual(args.workflow_kind, "tool_use")
        self.assertEqual(args.workflow_phase, "run")

        args = parser.parse_args(["--workflow-kind", "smoke", "--workflow-phase", "run"])
        self.assertEqual(args.workflow_kind, "smoke")
        self.assertEqual(args.workflow_phase, "run")

        args = parser.parse_args(
            [
                "--workflow-kind",
                "tool_use_eval",
                "--workflow-phase",
                "run",
                "--workflow-case-id",
                "tooluse_l0_file_read_001",
                "--workflow-level",
                "L0",
            ]
        )
        self.assertEqual(args.workflow_kind, "tool_use_eval")
        self.assertEqual(args.workflow_phase, "run")
        self.assertEqual(args.workflow_case_id, ["tooluse_l0_file_read_001"])
        self.assertEqual(args.workflow_level, ["L0"])

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

    def test_build_parser_parses_compare_workflow_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--workflow-kind", "healthcheck", "--workflow-phase", "compare", "--workflow-name", "agent-healthcheck"])

        self.assertEqual(args.workflow_kind, "healthcheck")
        self.assertEqual(args.workflow_phase, "compare")
        self.assertEqual(args.workflow_name, "agent-healthcheck")
        args = parser.parse_args(["--confirm-eval-case"])
        self.assertTrue(args.confirm_eval_case)

    def test_build_parser_parses_tooling_flags(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--eval-seed-status"])
        self.assertTrue(args.eval_seed_status)
        args = parser.parse_args(["--list-eval-seeds"])
        self.assertTrue(args.list_eval_seeds)
        args = parser.parse_args(["--eval-seed-report"])
        self.assertTrue(args.eval_seed_report)
        args = parser.parse_args(
            [
                "--ifeval-import-session",
                "session-1",
                "--ifeval-import-key",
                "1",
                "--ifeval-import-instruction-id",
                "rule:one",
                "--ifeval-import-kwargs",
                '{"foo":"bar"}',
            ]
        )
        self.assertEqual(args.ifeval_import_session, "session-1")
        self.assertEqual(args.ifeval_import_key, 1)
        self.assertEqual(args.ifeval_import_instruction_id, ["rule:one"])
        self.assertEqual(args.ifeval_import_kwargs, ['{"foo":"bar"}'])
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
        args = parser.parse_args(["--review-eval-case"])
        self.assertTrue(args.review_eval_case)
        args = parser.parse_args(["--review-skill"])
        self.assertTrue(args.review_skill)
        args = parser.parse_args(["--list-skills"])
        self.assertTrue(args.list_skills)
        args = parser.parse_args(["--skill-status"])
        self.assertTrue(args.skill_status)

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

    def test_main_uses_workspace_yolo_approval_provider(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app) as build_application_mock:
            with patch("sys.argv", ["navi-agent", "--yolo", "hello"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        _, kwargs = build_application_mock.call_args
        self.assertIsInstance(kwargs["approval_provider"], WorkspaceYoloApprovalProvider)

    def test_main_requires_message_without_interactive(self) -> None:
        with patch("sys.argv", ["navi-agent"]):
            with self.assertRaises(SystemExit):
                main()

    def test_import_ifeval_seed_writes_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            draft_path = Path(tmpdir) / "ifeval-drafts.jsonl"
            stdout = io.StringIO()
            messages = [
                Message(role="user", content="Write a summary."),
                Message(role="assistant", content="summary output"),
            ]

            with patch("navi_agent.cli.get_state_db_path", return_value=Path(tmpdir) / "state.db"):
                with patch("navi_agent.cli.get_ifeval_drafts_path", return_value=draft_path):
                    with patch("navi_agent.cli.SQLiteSessionStore", return_value=FakeSessionStore(messages)):
                        with patch(
                            "sys.argv",
                            [
                                "navi-agent",
                                "--ifeval-import-session",
                                "session-1",
                                "--ifeval-import-key",
                                "42",
                                "--ifeval-import-instruction-id",
                                "rule:one",
                                "--ifeval-import-kwargs",
                                '{"foo": "bar"}',
                            ],
                        ):
                            with redirect_stdout(stdout):
                                exit_code = main()

            self.assertEqual(exit_code, 0)
            self.assertIn("ifeval_draft_written:", stdout.getvalue())
            self.assertTrue(draft_path.exists())
            draft_seed = EvalSeedStore(draft_path).list_recent(limit=None)[0]
            self.assertEqual(draft_seed.key, 42)
            self.assertEqual(draft_seed.prompt, "Write a summary.")
            self.assertEqual(draft_seed.output, "summary output")
            self.assertEqual(draft_seed.instruction_id_list, ["rule:one"])
            self.assertEqual(draft_seed.kwargs, [{"foo": "bar"}])

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

    def test_main_runs_unified_healthcheck_run_workflow(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        workflow_result = type(
            "WorkflowResult",
            (),
            {
                "workflow": type("Workflow", (), {"name": "agent-healthcheck"})(),
                "session_id": "wf-1",
                "steps": [
                    type(
                        "StepResult",
                        (),
                        {
                            "task_name": "config-check",
                            "trace_id": "trace-1",
                            "runtime_result": RuntimeResult(session_id="wf-1", status="success", final_response="done"),
                        },
                    )()
                ],
            },
        )()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("navi_agent.cli.run_healthcheck_workflow", return_value=workflow_result) as run_mock:
                with patch(
                    "sys.argv",
                    ["navi-agent", "--workflow-kind", "healthcheck", "--workflow-phase", "run", "--workflow-name", "agent-healthcheck"],
                ):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("workflow: agent-healthcheck", stdout.getvalue())
        self.assertIn("done", stdout.getvalue())
        run_mock.assert_called_once()

    def test_main_runs_unified_healthcheck_compare_workflow(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli._run_evolution_workflow", return_value=0) as compare_mock:
            with patch(
                "sys.argv",
                [
                    "navi-agent",
                    "--workflow-kind",
                    "healthcheck",
                    "--workflow-phase",
                    "compare",
                    "--workflow-name",
                    "agent-healthcheck",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        compare_mock.assert_called_once()

    def test_main_runs_unified_ifeval_review_workflow(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli._review_ifeval_draft", return_value=0) as review_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "ifeval", "--workflow-phase", "review"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        review_mock.assert_called_once_with()

    def test_main_runs_unified_ifeval_report_workflow(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli._print_ifeval_status", return_value=0) as report_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "ifeval", "--workflow-phase", "report"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        report_mock.assert_called_once_with()

    def test_main_runs_unified_smoke_workflows(self) -> None:
        with patch("navi_agent.cli._run_smoke_workflow", return_value=0) as run_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "smoke", "--workflow-phase", "run"]):
                self.assertEqual(main(), 0)
        run_mock.assert_called_once_with()

        with patch("navi_agent.cli._print_smoke_status", return_value=0) as report_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "smoke", "--workflow-phase", "report"]):
                self.assertEqual(main(), 0)
        report_mock.assert_called_once_with()

    def test_main_runs_unified_tool_use_workflows(self) -> None:
        with patch("navi_agent.cli._run_tool_use_eval", return_value=0) as run_mock:
            with patch(
                "sys.argv",
                [
                    "navi-agent",
                    "--workflow-kind",
                    "tool_use",
                    "--workflow-phase",
                    "run",
                    "--workflow-case-id",
                    "case-1",
                    "--workflow-level",
                    "L0",
                ],
            ):
                self.assertEqual(main(), 0)
        run_mock.assert_called_once_with(case_ids=["case-1"], levels=["L0"])

        with patch("navi_agent.cli._print_tool_use_status", return_value=0) as report_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "tool_use", "--workflow-phase", "report"]):
                self.assertEqual(main(), 0)
        report_mock.assert_called_once_with()

    def test_main_runs_unified_tool_use_eval_workflows(self) -> None:
        with patch("navi_agent.cli._run_tool_use_llm_eval", return_value=0) as run_mock:
            with patch(
                "sys.argv",
                [
                    "navi-agent",
                    "--workflow-kind",
                    "tool_use_eval",
                    "--workflow-phase",
                    "run",
                    "--workflow-case-id",
                    "case-llm",
                    "--workflow-level",
                    "L1",
                ],
            ):
                self.assertEqual(main(), 0)
        run_mock.assert_called_once_with(case_ids=["case-llm"], levels=["L1"])

        with patch("navi_agent.cli._print_tool_use_eval_status", return_value=0) as report_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "tool_use_eval", "--workflow-phase", "report"]):
                self.assertEqual(main(), 0)
        report_mock.assert_called_once_with()

    def test_main_prints_eval_seed_status(self) -> None:
        stdout = io.StringIO()
        fake_store = type(
            "SeedStore",
            (),
            {
                "describe": lambda self: {
                    "path": "/tmp/ifeval_seed.jsonl",
                    "exists": True,
                    "count": 2,
                    "passed_count": 1,
                    "failed_count": 1,
                    "pending_count": 0,
                    "keys": [1001, 1019],
                },
                "validate": lambda self: [],
            },
        )()

        with patch("navi_agent.cli.EvalSeedStore", return_value=fake_store):
            with patch("sys.argv", ["navi-agent", "--eval-seed-status"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("eval_seed_count: 2", stdout.getvalue())
        self.assertIn("eval_seed_passed_count: 1", stdout.getvalue())
        self.assertIn("eval_seed_failed_count: 1", stdout.getvalue())

    def test_main_lists_eval_seeds(self) -> None:
        stdout = io.StringIO()
        fake_store = type(
            "SeedStore",
            (),
            {
                "list_recent": lambda self, limit=None: [
                    type(
                        "Seed",
                        (),
                        {"key": 1001, "pass_fail": True, "session_id": "ifeval-002", "prompt": "prompt"},
                    )()
                ]
            },
        )()

        with patch("navi_agent.cli.EvalSeedStore", return_value=fake_store):
            with patch("sys.argv", ["navi-agent", "--list-eval-seeds"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("1001 [pass] ifeval-002: prompt", stdout.getvalue())

    def test_main_writes_eval_seed_report(self) -> None:
        stdout = io.StringIO()
        fake_writer = type(
            "Writer",
            (),
            {
                "write_report": lambda self, seed_store: "/tmp/eval-seed-report",
            },
        )()
        fake_store = type(
            "ReportStore",
            (),
            {
                "get_latest": lambda self: type("Record", (), {"count": 2, "pass_rate": 0.5})(),
            },
        )()

        with patch("navi_agent.cli.EvalSeedReportWriter", return_value=fake_writer):
            with patch("navi_agent.cli.EvalSeedReportStore", return_value=fake_store):
                with patch("sys.argv", ["navi-agent", "--eval-seed-report"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("eval_seed_report_path: /tmp/eval-seed-report", stdout.getvalue())
        self.assertIn("eval_seed_count: 2", stdout.getvalue())
        self.assertIn("eval_seed_pass_rate: 0.5", stdout.getvalue())

    def test_main_runs_ifeval(self) -> None:
        stdout = io.StringIO()
        fake_store = type(
            "SeedStore",
            (),
            {
                "path": "/tmp/ifeval_seed.jsonl",
                "list_recent": lambda self, limit=None: [
                    EvalSeed(
                        key=1001,
                        prompt="prompt one",
                        instruction_id_list=["punctuation:no_comma"],
                        kwargs=[{}],
                        session_id="ifeval-001",
                        output="done",
                        pass_fail=True,
                    ),
                    EvalSeed(
                        key=1019,
                        prompt="prompt two",
                        instruction_id_list=["change_case:english_lowercase"],
                        kwargs=[{}],
                        session_id="ifeval-002",
                        output="done",
                        pass_fail=True,
                    ),
                ],
            },
        )()
        fake_writer = type(
            "Writer",
            (),
            {
                "write_run_report": lambda self, seed_store, results: "/tmp/ifeval-run",
            },
        )()

        with patch("navi_agent.cli.EvalSeedStore", return_value=fake_store):
            with patch("navi_agent.cli.IfevalRunWriter", return_value=fake_writer):
                with patch("navi_agent.cli.build_application", return_value=FakeApp()):
                    with patch(
                        "sys.argv",
                        ["navi-agent", "--workflow-kind", "ifeval", "--workflow-phase", "run"],
                    ):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("1001 [pass] ifeval-001: score=1.0", stdout.getvalue())
        self.assertIn("1019 [pass] ifeval-002: score=1.0", stdout.getvalue())
        self.assertIn("ifeval_report_path: /tmp/ifeval-run", stdout.getvalue())
        self.assertIn("ifeval_pass_rate: 1.0", stdout.getvalue())

    def test_main_prints_ifeval_status(self) -> None:
        stdout = io.StringIO()
        fake_store = type(
            "RunStore",
            (),
            {
                "get_latest": lambda self: type(
                    "RunRecord",
                    (),
                    {
                        "report_path": "/tmp/ifeval-reports/20260704-090000",
                        "seed_path": "/tmp/ifeval_seed.jsonl",
                        "count": 2,
                        "passed_count": 1,
                        "failed_count": 1,
                        "pass_rate": 0.5,
                        "created_at": "20260704-090000",
                    },
                )(),
            },
        )()

        with patch("navi_agent.cli.IfevalRunStore", return_value=fake_store):
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "ifeval", "--workflow-phase", "report"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("ifeval_report_root:", stdout.getvalue())
        self.assertIn("ifeval_latest_report_path: /tmp/ifeval-reports/20260704-090000", stdout.getvalue())
        self.assertIn("ifeval_latest_pass_rate: 0.5", stdout.getvalue())

    def test_main_shows_prompt_overlay_status(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.PromptOverlayStore") as overlay_cls:
            overlay_cls.return_value.describe.return_value = {
                "path": "/tmp/prompt-overlay.md",
                "exists": True,
                "candidate_count": 2,
                "candidate_ids": ["c1", "c2"],
                "workflow_names": ["agent-healthcheck"],
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
                "agent-healthcheck": [
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
        self.assertIn("workflow: agent-healthcheck", stdout.getvalue())
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

    def test_main_reviews_and_applies_skill_candidate(self) -> None:
        fake_app = FakeApp()
        fake_app.saved_candidates.append(
            EvolutionCandidate(
                target="skill",
                summary="Create README summary skill",
                rationale="Successful tool trace",
                candidate_id="skill-1",
                metadata={
                    "skill_name": "readme-summary",
                    "source_session_id": "session-1",
                    "source_trace_id": "trace-1",
                    "tool_names": ["read_file", "bash"],
                    "reviewer": "llm",
                    "skill_content": "# README Summary\n\n## When To Use\n\nUse for README summaries.",
                },
            )
        )
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("builtins.input", return_value="y"):
                with patch("navi_agent.cli.SmokeWorkflowService") as smoke_cls:
                    smoke_cls.return_value.run.return_value = SmokeRunSummary(
                        count=1,
                        passed_count=1,
                        failed_count=0,
                        pass_rate=1.0,
                        results=[SmokeCheckResult(name="doctor", passed=True, summary="doctor ok")],
                        report_path=Path("/tmp/smoke/report.json"),
                    )
                    with patch("sys.argv", ["navi-agent", "--review-skill"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("skill review:", stdout.getvalue())
        self.assertIn("skill_name: readme-summary", stdout.getvalue())
        self.assertIn("reviewer: llm", stdout.getvalue())
        self.assertIn("source_session_id: session-1", stdout.getvalue())
        self.assertIn("source_trace_id: trace-1", stdout.getvalue())
        self.assertIn("tool_names: read_file,bash", stdout.getvalue())
        self.assertIn("--- BEGIN SKILL.md ---", stdout.getvalue())
        self.assertIn("# README Summary", stdout.getvalue())
        self.assertIn("--- END SKILL.md ---", stdout.getvalue())
        self.assertIn("skill_apply_gate: smoke", stdout.getvalue())
        self.assertIn("skill_apply_gate_failed_count: 0", stdout.getvalue())
        self.assertIn("candidate_status: verified", stdout.getvalue())
        self.assertIs(fake_app.applied_candidate, fake_app.saved_candidates[0])

    def test_main_reviews_and_rejects_skill_candidate(self) -> None:
        fake_app = FakeApp()
        fake_app.saved_candidates.append(
            EvolutionCandidate(
                target="skill",
                summary="Create README summary skill",
                rationale="Successful tool trace",
                candidate_id="skill-1",
                metadata={"skill_name": "readme-summary"},
            )
        )
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("builtins.input", return_value="n"):
                with patch("sys.argv", ["navi-agent", "--review-skill"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("candidate_status: rejected", stdout.getvalue())
        self.assertEqual(fake_app.saved_candidates[0].status, "rejected")

    def test_main_marks_skill_candidate_regressed_when_apply_gate_fails(self) -> None:
        fake_app = FakeApp()
        fake_app.saved_candidates.append(
            EvolutionCandidate(
                target="skill",
                summary="Create README summary skill",
                rationale="Successful tool trace",
                candidate_id="skill-1",
                metadata={
                    "skill_name": "readme-summary",
                    "skill_content": "# README Summary\n",
                },
            )
        )
        stdout = io.StringIO()

        with patch("navi_agent.cli.build_application", return_value=fake_app):
            with patch("builtins.input", return_value="y"):
                with patch("navi_agent.cli.SmokeWorkflowService") as smoke_cls:
                    smoke_cls.return_value.run.return_value = SmokeRunSummary(
                        count=1,
                        passed_count=0,
                        failed_count=1,
                        pass_rate=0.0,
                        results=[SmokeCheckResult(name="doctor", passed=False, summary="doctor failed")],
                        report_path=Path("/tmp/smoke/report.json"),
                    )
                    with patch("sys.argv", ["navi-agent", "--review-skill"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("skill_apply_gate_failed_count: 1", stdout.getvalue())
        self.assertIn("doctor [fail] doctor failed", stdout.getvalue())
        self.assertIn("candidate_status: regressed_after_apply", stdout.getvalue())
        self.assertEqual(fake_app.saved_candidates[0].status, "regressed_after_apply")

    def test_main_lists_skills(self) -> None:
        stdout = io.StringIO()
        records = [
            type(
                "SkillRecord",
                (),
                {
                    "name": "readme-summary",
                    "description": "Summarize README files",
                },
            )()
        ]

        with patch("navi_agent.cli.get_skills_dir", return_value=Path("/tmp/skills")):
            with patch("navi_agent.cli.FileSkillStore") as store_cls:
                store_cls.return_value.list.return_value = records
                with patch("sys.argv", ["navi-agent", "--list-skills"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("skills_dir: /tmp/skills", stdout.getvalue())
        self.assertIn("skill_count: 1", stdout.getvalue())
        self.assertIn("- readme-summary: Summarize README files", stdout.getvalue())

    def test_main_prints_skill_status(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.get_skills_dir", return_value=Path("/tmp/skills")):
            with patch("navi_agent.cli.get_trace_store_path", return_value=Path("/tmp/traces.jsonl")):
                with patch("navi_agent.cli.SkillUsageService") as service_cls:
                    service_cls.return_value.summarize.return_value = [
                        SkillUsageRecord(
                            name="readme-summary",
                            description="Summarize README files",
                            injected_count=2,
                            last_injected_at="2026-07-11T11:00:00+00:00",
                        )
                    ]
                    with patch("sys.argv", ["navi-agent", "--skill-status"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("skills_dir: /tmp/skills", stdout.getvalue())
        self.assertIn("trace_store_path: /tmp/traces.jsonl", stdout.getvalue())
        self.assertIn("skill_count: 1", stdout.getvalue())
        self.assertIn("- readme-summary: Summarize README files", stdout.getvalue())
        self.assertIn("injected_count: 2", stdout.getvalue())
        self.assertIn("last_injected_at: 2026-07-11T11:00:00+00:00", stdout.getvalue())

    def test_main_prints_skill_curator_status(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.get_skills_dir", return_value=Path("/tmp/skills")):
            with patch("navi_agent.cli.get_trace_store_path", return_value=Path("/tmp/traces.jsonl")):
                with patch("navi_agent.cli.SkillCuratorStatusService") as service_cls:
                    service_cls.return_value.summarize.return_value = SkillCuratorStatus(
                        skill_count=1,
                        agent_created_count=1,
                        manual_count=0,
                        unused_agent_created_count=1,
                        records=[
                            SkillCuratorRecord(
                                name="readme-summary",
                                description="Summarize README files",
                                origin="agent",
                                injected_count=0,
                                candidate_action="review-unused",
                            )
                        ],
                    )
                    with patch("sys.argv", ["navi-agent", "--skill-curator-status"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("skills_dir: /tmp/skills", stdout.getvalue())
        self.assertIn("agent_created_count: 1", stdout.getvalue())
        self.assertIn("unused_agent_created_count: 1", stdout.getvalue())
        self.assertIn("- readme-summary: Summarize README files", stdout.getvalue())
        self.assertIn("origin: agent", stdout.getvalue())
        self.assertIn("candidate_action: review-unused", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
