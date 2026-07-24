import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from navi_agent.evolution import (
    EvalSeed,
    EvolutionCandidate,
    SkillCuratorArchiveResult,
    SkillCuratorRecord,
    SkillCuratorStatus,
    ToolUseEvalCaseStore,
    SkillUsageRecord,
)
from navi_agent.evolution import EvalSeedStore
from navi_agent.cli.main import (
    _read_interactive_message,
    _run_interactive,
    _run_persistent_interactive,
    build_parser,
    main,
)
from navi_agent.runtime import (
    CliApprovalProvider,
    DeferredApprovalProvider,
    Message,
    RuntimeEvent,
    RuntimeResult,
    WorkspaceYoloApprovalProvider,
)
from navi_agent.runtime.tasks.cron import CronRunRecord
from navi_agent.evolution.evals.smoke import SmokeCheckResult, SmokeRunSummary


class FakeApp:
    def __init__(self) -> None:
        self.calls = []
        self.event_subscribers = []
        self.saved_candidates = []
        self.saved_eval_cases = []
        self.applied_candidate = None
        self.rolled_back_candidate = None

    def handle(self, request, *, event_subscribers=None):
        self.calls.append(request)
        self.event_subscribers.append(event_subscribers)
        return RuntimeResult(
            session_id=request.session_id or "generated",
            status="success",
            final_response="done",
        )

    def add_candidate(self, candidate) -> None:
        self.saved_candidates.append(candidate)

    def add_eval_case(self, eval_case) -> None:
        self.saved_eval_cases.append(eval_case)

    def cancel_session(self, session_id, *, reason="user_requested") -> bool:
        return False

    def resolve_interaction(self, session_id, *, approved):
        return None

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

    def rollback_candidate(self, candidate_id, status="regressed_after_apply", review_note=None):
        candidate = self.update_candidate_status(candidate_id, status, review_note=review_note)
        if candidate is not None:
            self.rolled_back_candidate = candidate
        return candidate

    def get_background_review_status(self):
        return getattr(self, "background_review_status", None)


class FakeSessionStore:
    def __init__(self, messages):
        self._messages = messages

    def snapshot(self, session):
        return list(self._messages)


class FakePromptSession:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = []

    def prompt(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.message


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
        self.assertIsNone(args.subcommand)
        self.assertFalse(args.interactive)

    def test_build_parser_parses_interactive_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--interactive"])

        self.assertTrue(args.interactive)
        self.assertIsNone(args.message)
        self.assertIsNone(args.subcommand)

    def test_build_parser_parses_yolo_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--yolo", "hello"])
        short_args = parser.parse_args(["-y", "hello"])

        self.assertTrue(args.yolo)
        self.assertTrue(short_args.yolo)

    def test_build_parser_parses_repeated_add_dir_flags(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            args = parser.parse_args(["--add-dir", first, "--add-dir", second, "hello"])

        self.assertEqual(args.add_dir, [Path(first).resolve(), Path(second).resolve()])

    def test_build_parser_rejects_missing_add_dir(self) -> None:
        parser = build_parser()
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--add-dir", "/missing/navi-agent-directory", "hello"])

        self.assertIn("directory does not exist", stderr.getvalue())

    def test_build_parser_parses_banner_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--banner"])

        self.assertTrue(args.banner)

    def test_build_parser_parses_doctor_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--doctor"])

        self.assertTrue(args.doctor)
        self.assertIsNone(args.message)
        args = parser.parse_args(["doctor", "--doctor-gateway", "weixin"])
        self.assertEqual(args.message, "doctor")
        self.assertIsNone(args.subcommand)
        self.assertEqual(args.doctor_gateway, "weixin")

        args = parser.parse_args(["gateway", "start"])
        self.assertEqual(args.message, "gateway")
        self.assertEqual(args.subcommand, "start")

        args = parser.parse_args(["cron", "run", "--cron-poll-interval", "2"])
        self.assertEqual(args.message, "cron")
        self.assertEqual(args.subcommand, "run")
        self.assertEqual(args.cron_poll_interval, 2)

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
        args = parser.parse_args(["--runtime-events", "--session-id", "s1", "--runtime-run-id", "r1"])
        self.assertTrue(args.runtime_events)
        self.assertEqual(args.session_id, "s1")
        self.assertEqual(args.runtime_run_id, "r1")
        args = parser.parse_args(["--runtime-health", "--session-id", "s1"])
        self.assertTrue(args.runtime_health)
        self.assertEqual(args.session_id, "s1")
        args = parser.parse_args(["--runtime-export-tool-use-case", "--session-id", "s1"])
        self.assertTrue(args.runtime_export_tool_use_case)
        self.assertEqual(args.session_id, "s1")
        args = parser.parse_args(["--runtime-import-tool-use-case", "--session-id", "s1"])
        self.assertTrue(args.runtime_import_tool_use_case)
        self.assertEqual(args.session_id, "s1")

    def test_main_builds_application_and_prints_result(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app) as build_application_mock:
            with patch("sys.argv", ["navi-agent", "--user-id", "u1", "hello"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "done")
        build_application_mock.assert_called_once()
        _, kwargs = build_application_mock.call_args
        self.assertEqual(kwargs["default_system_prompt"], None)
        self.assertIsInstance(kwargs["approval_provider"], CliApprovalProvider)
        self.assertEqual(kwargs["additional_workspace_roots"], [])
        self.assertEqual(fake_app.calls[0].user_id, "u1")
        self.assertEqual(fake_app.calls[0].message, "hello")

    def test_main_passes_added_directories_to_application(self) -> None:
        fake_app = FakeApp()
        with tempfile.TemporaryDirectory() as added_dir:
            with patch("navi_agent.cli.main.build_application", return_value=fake_app) as build_application_mock:
                with patch("sys.argv", ["navi-agent", "--add-dir", added_dir, "hello"]):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        _, kwargs = build_application_mock.call_args
        self.assertEqual(kwargs["additional_workspace_roots"], [Path(added_dir).resolve()])

    def test_main_uses_workspace_yolo_approval_provider(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app) as build_application_mock:
            with patch("sys.argv", ["navi-agent", "--yolo", "hello"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        _, kwargs = build_application_mock.call_args
        self.assertIsInstance(kwargs["approval_provider"], WorkspaceYoloApprovalProvider)

    def test_main_defaults_to_interactive_mode(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("builtins.input", side_effect=EOFError):
                with patch("sys.argv", ["navi-agent"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("Interactive session:", stdout.getvalue())
        self.assertEqual(fake_app.calls, [])

    def test_main_interactive_uses_deferred_approval_provider(self) -> None:
        fake_app = FakeApp()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app) as build_application:
            with patch("builtins.input", side_effect=EOFError):
                with patch("sys.argv", ["navi-agent"]):
                    main()

        _, kwargs = build_application.call_args
        self.assertIsInstance(kwargs["approval_provider"], DeferredApprovalProvider)
        self.assertIsNotNone(kwargs["interaction_store"])

    def test_import_ifeval_seed_writes_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            draft_path = Path(tmpdir) / "ifeval-drafts.jsonl"
            stdout = io.StringIO()
            messages = [
                Message(role="user", content="Write a summary."),
                Message(role="assistant", content="summary output"),
            ]

            with patch("navi_agent.cli.main.get_state_db_path", return_value=Path(tmpdir) / "state.db"):
                with patch("navi_agent.cli.main.get_ifeval_drafts_path", return_value=draft_path):
                    with patch("navi_agent.cli.main.SQLiteSessionStore", return_value=FakeSessionStore(messages)):
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
        with patch("navi_agent.cli.main.run_doctor", return_value=0) as run_doctor_mock:
            with patch("sys.argv", ["navi-agent", "--doctor"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        run_doctor_mock.assert_called_once_with(gateway=None)

    def test_main_runs_doctor_command(self) -> None:
        with patch("navi_agent.cli.main.run_doctor", return_value=0) as run_doctor_mock:
            with patch("sys.argv", ["navi-agent", "doctor", "--doctor-gateway", "weixin"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        run_doctor_mock.assert_called_once_with(gateway="weixin")

    def test_main_init_creates_default_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            with patch.dict("os.environ", {"NAVI_HOME": tmpdir}, clear=True):
                with patch("sys.argv", ["navi-agent", "init"]):
                    with redirect_stdout(stdout):
                        exit_code = main()
            config_path = Path(tmpdir) / "config.yaml"
            self.assertEqual(exit_code, 0)
            self.assertIn("config_created:", stdout.getvalue())
            self.assertTrue(config_path.exists())
            config_text = config_path.read_text(encoding="utf-8")
            self.assertIn("gateway:", config_text)
            self.assertIn("context_limit_tokens: 128000", config_text)

    def test_main_init_does_not_overwrite_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("model:\n  name: custom\n", encoding="utf-8")
            stdout = io.StringIO()
            with patch.dict("os.environ", {"NAVI_HOME": tmpdir}, clear=True):
                with patch("sys.argv", ["navi-agent", "init"]):
                    with redirect_stdout(stdout):
                        exit_code = main()
            self.assertEqual(exit_code, 0)
            self.assertIn("config_exists:", stdout.getvalue())
            self.assertEqual(config_path.read_text(encoding="utf-8"), "model:\n  name: custom\n")

    def test_main_gateway_start_runs_weixin_gateway(self) -> None:
        fake_app = FakeApp()
        config = {
            "gateway": {
                "weixin": {
                    "token": "token",
                    "account_id": "account-1",
                    "base_url": "http://127.0.0.1:9001",
                }
            }
        }
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("navi_agent.cli.main.load_config", return_value=config):
                with patch("navi_agent.cli.main.ILinkGateway") as gateway_cls:
                    with patch("sys.argv", ["navi-agent", "gateway", "start"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("weixin_ilink_polling: account_id=account-1", stdout.getvalue())
        gateway_cls.return_value.run_forever.assert_called_once_with()

    def test_main_cron_run_processes_due_jobs(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app) as build_app_mock:
            with patch("navi_agent.cli.main.CronSchedulerService") as scheduler_cls:
                scheduler_cls.return_value.run_due.return_value = [
                    CronRunRecord(
                        job_id="job-1",
                        session_id="s1",
                        status="success",
                        final_response="done",
                        ran_at="2026-07-21T09:00:00+00:00",
                    )
                ]
                with patch("navi_agent.cli.main.get_cron_jobs_path", return_value=Path("/tmp/jobs.json")):
                    with patch("navi_agent.cli.main.get_cron_tick_lock_path", return_value=Path("/tmp/.tick.lock")):
                        with patch("sys.argv", ["navi-agent", "cron", "run"]):
                            with redirect_stdout(stdout):
                                exit_code = main()

        self.assertEqual(exit_code, 0)
        build_app_mock.assert_called_once()
        self.assertEqual(build_app_mock.call_args.kwargs["disabled_toolsets"], ["scheduler"])
        scheduler_cls.assert_called_once()
        self.assertEqual(scheduler_cls.call_args.kwargs["lock_path"], Path("/tmp/.tick.lock"))
        scheduler_cls.return_value.run_due.assert_called_once_with(app=fake_app)
        self.assertIn("cron_jobs_path: /tmp/jobs.json", stdout.getvalue())
        self.assertIn("cron_due_count: 1", stdout.getvalue())
        self.assertIn("- job-1 [success] session=s1", stdout.getvalue())

    def test_main_rejects_legacy_start_command(self) -> None:
        stderr = io.StringIO()

        with patch("sys.argv", ["navi-agent", "start"]):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("navi-agent gateway start", stderr.getvalue())

    def test_main_requires_weixin_token_for_gateway_mode(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.load_config", return_value={}):
            with patch("sys.argv", ["navi-agent", "--gateway", "weixin"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("weixin token is required", stdout.getvalue())
        self.assertIn("doctor --doctor-gateway weixin", stdout.getvalue())

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

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("navi_agent.cli.main.load_config", return_value=config):
                with patch("navi_agent.cli.main.ILinkGateway") as gateway_cls:
                    with patch("sys.argv", ["navi-agent", "--gateway", "weixin"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("weixin_ilink_polling: account_id=account-1", stdout.getvalue())
        gateway_cls.return_value.run_forever.assert_called_once_with()

    def test_main_requires_account_id_for_weixin_ilink_mode(self) -> None:
        stdout = io.StringIO()

        with patch(
            "navi_agent.cli.main.load_config",
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
        self.assertIn("doctor --doctor-gateway weixin", stdout.getvalue())

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

        with patch("navi_agent.cli.main.WeixinPairingStore", return_value=fake_store):
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

        with patch("navi_agent.cli.main.WeixinPairingStore", return_value=fake_store):
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

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("navi_agent.cli.main.run_healthcheck_workflow", return_value=workflow_result) as run_mock:
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

        with patch("navi_agent.cli.main._run_evolution_workflow", return_value=0) as compare_mock:
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

        with patch("navi_agent.cli.main._review_ifeval_draft", return_value=0) as review_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "ifeval", "--workflow-phase", "review"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        review_mock.assert_called_once_with()

    def test_main_runs_unified_ifeval_report_workflow(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.main._print_ifeval_status", return_value=0) as report_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "ifeval", "--workflow-phase", "report"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        report_mock.assert_called_once_with()

    def test_main_runs_unified_smoke_workflows(self) -> None:
        with patch("navi_agent.cli.main._run_smoke_workflow", return_value=0) as run_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "smoke", "--workflow-phase", "run"]):
                self.assertEqual(main(), 0)
        run_mock.assert_called_once_with()

        with patch("navi_agent.cli.main._print_smoke_status", return_value=0) as report_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "smoke", "--workflow-phase", "report"]):
                self.assertEqual(main(), 0)
        report_mock.assert_called_once_with()

    def test_main_runs_unified_tool_use_workflows(self) -> None:
        with patch("navi_agent.cli.main._run_tool_use_eval", return_value=0) as run_mock:
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

        with patch("navi_agent.cli.main._print_tool_use_status", return_value=0) as report_mock:
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "tool_use", "--workflow-phase", "report"]):
                self.assertEqual(main(), 0)
        report_mock.assert_called_once_with()

    def test_main_runs_unified_tool_use_eval_workflows(self) -> None:
        with patch("navi_agent.cli.main._run_tool_use_llm_eval", return_value=0) as run_mock:
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

        with patch("navi_agent.cli.main._print_tool_use_eval_status", return_value=0) as report_mock:
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

        with patch("navi_agent.cli.main.EvalSeedStore", return_value=fake_store):
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

        with patch("navi_agent.cli.main.EvalSeedStore", return_value=fake_store):
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

        with patch("navi_agent.cli.main.EvalSeedReportWriter", return_value=fake_writer):
            with patch("navi_agent.cli.main.EvalSeedReportStore", return_value=fake_store):
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

        with patch("navi_agent.cli.main.EvalSeedStore", return_value=fake_store):
            with patch("navi_agent.cli.main.IfevalRunWriter", return_value=fake_writer):
                with patch("navi_agent.cli.main.build_application", return_value=FakeApp()):
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

        with patch("navi_agent.cli.main.IfevalRunStore", return_value=fake_store):
            with patch("sys.argv", ["navi-agent", "--workflow-kind", "ifeval", "--workflow-phase", "report"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("ifeval_report_root:", stdout.getvalue())
        self.assertIn("ifeval_latest_report_path: /tmp/ifeval-reports/20260704-090000", stdout.getvalue())
        self.assertIn("ifeval_latest_pass_rate: 0.5", stdout.getvalue())

    def test_main_shows_prompt_overlay_status(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.PromptOverlayStore") as overlay_cls:
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

        with patch("navi_agent.cli.main.PromptOverlayStore") as overlay_cls:
            overlay_cls.return_value.get.return_value = "overlay text"
            with patch("sys.argv", ["navi-agent", "--show-prompt-overlay"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "overlay text")

    def test_main_lists_prompt_overlay_entries(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.PromptOverlayStore") as overlay_cls:
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

        with patch("navi_agent.cli.main.PromptOverlayStore") as overlay_cls:
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

        with patch("navi_agent.cli.main.PromptOverlayStore") as overlay_cls:
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
        self.assertTrue(all(len(items or []) == 1 for items in fake_app.event_subscribers))
        self.assertIn("powered by xushun", stdout.getvalue())
        self.assertIn("Interactive session: s1", stdout.getvalue())
        self.assertIn("Shift+Enter for a newline", stdout.getvalue())
        self.assertEqual(stdout.getvalue().strip().splitlines()[-2:], ["done", "done"])

    def test_run_interactive_streams_response_without_printing_it_twice(self) -> None:
        class StreamingApp(FakeApp):
            def handle(self, request, *, event_subscribers=None):
                self.calls.append(request)
                self.event_subscribers.append(event_subscribers)
                for sequence, delta in enumerate(["hello ", "world"], start=1):
                    event = RuntimeEvent(
                        session_id=request.session_id,
                        user_id=request.user_id,
                        run_id="run-1",
                        sequence=sequence,
                        kind="delta",
                        source="model",
                        name="model.delta",
                        item_id="model:1",
                        metadata={"delta": delta},
                    )
                    for subscriber in event_subscribers or []:
                        subscriber.handle(event)
                return RuntimeResult(
                    session_id=request.session_id,
                    status="success",
                    final_response="hello world",
                )

        stdout = io.StringIO()
        with patch("builtins.input", side_effect=["hello", "exit"]):
            with redirect_stdout(stdout):
                exit_code = _run_interactive(
                    app=StreamingApp(),
                    user_id="u1",
                    session_id="s1",
                    system_prompt=None,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().count("hello world"), 1)

    def test_persistent_interactive_steers_active_run(self) -> None:
        from threading import Event

        first_started = Event()
        release_first = Event()
        second_completed = Event()

        class ControlledApp(FakeApp):
            def __init__(self) -> None:
                super().__init__()
                self.cancel_calls = []

            def handle(self, request, *, event_subscribers=None):
                self.calls.append(request)
                if len(self.calls) == 1:
                    first_started.set()
                    release_first.wait(timeout=2)
                    return RuntimeResult(
                        session_id=request.session_id,
                        status="cancelled",
                        final_response="cancelled",
                    )
                second_completed.set()
                return RuntimeResult(
                    session_id=request.session_id,
                    status="success",
                    final_response="steered",
                )

            def cancel_session(self, session_id, *, reason="user_requested") -> bool:
                self.cancel_calls.append((session_id, reason))
                release_first.set()
                return True

        class Prompt:
            def __init__(self) -> None:
                self.notices = []
                self.responses = []
                self.busy = []

            def run(self, submit, *, on_approval=None, first_message=None):
                submit(first_message)
                assert first_started.wait(timeout=2)
                submit("/steer use the new plan")
                assert second_completed.wait(timeout=2)

            def set_busy(self, busy):
                self.busy.append(busy)

            def handle(self, _event):
                pass

            def complete_response(self, response):
                self.responses.append(response)

            def show_notice(self, text):
                self.notices.append(text)

            def exit(self):
                pass

        app = ControlledApp()
        prompt = Prompt()

        exit_code = _run_persistent_interactive(
            app=app,
            prompt_session=prompt,
            user_id="u1",
            session_id="s1",
            system_prompt=None,
            first_message="original task",
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [request.message for request in app.calls],
            ["original task", "use the new plan"],
        )
        self.assertEqual(app.cancel_calls, [("s1", "user_steer")])
        self.assertIn("Steering current task…", prompt.notices)

    def test_persistent_interactive_stops_active_run(self) -> None:
        from threading import Event

        started = Event()
        stopped = Event()

        class ControlledApp(FakeApp):
            def __init__(self) -> None:
                super().__init__()
                self.cancel_calls = []

            def handle(self, request, *, event_subscribers=None):
                started.set()
                stopped.wait(timeout=2)
                return RuntimeResult(
                    session_id=request.session_id,
                    status="cancelled",
                    final_response="cancelled",
                )

            def cancel_session(self, session_id, *, reason="user_requested") -> bool:
                self.cancel_calls.append((session_id, reason))
                stopped.set()
                return True

        class Prompt:
            def __init__(self) -> None:
                self.notices = []

            def run(self, submit, *, on_approval=None, first_message=None):
                submit(first_message)
                assert started.wait(timeout=2)
                submit("/stop")
                assert stopped.wait(timeout=2)

            def set_busy(self, _busy):
                pass

            def handle(self, _event):
                pass

            def complete_response(self, _response):
                pass

            def show_notice(self, text):
                self.notices.append(text)

            def exit(self):
                pass

        app = ControlledApp()
        prompt = Prompt()

        _run_persistent_interactive(
            app=app,
            prompt_session=prompt,
            user_id="u1",
            session_id="s1",
            system_prompt=None,
            first_message="long task",
        )

        self.assertEqual(app.cancel_calls, [("s1", "user_stop")])
        self.assertIn("Stopping current task…", prompt.notices)

    def test_persistent_interactive_resolves_selected_approval(self) -> None:
        from threading import Event

        completed = Event()

        class ApprovalApp(FakeApp):
            def __init__(self) -> None:
                super().__init__()
                self.resolve_calls = []

            def resolve_interaction(self, session_id, *, approved):
                self.resolve_calls.append((session_id, approved))
                return SimpleNamespace(kind="approval", tool_name="bash")

            def handle(self, request, *, event_subscribers=None):
                self.calls.append(request)
                completed.set()
                return RuntimeResult(
                    session_id=request.session_id,
                    status="success",
                    final_response="denied",
                )

        class Prompt:
            def __init__(self) -> None:
                self.notices = []

            def run(self, submit, *, on_approval=None, first_message=None):
                assert on_approval is not None
                on_approval(False)
                assert completed.wait(timeout=2)

            def set_busy(self, _busy):
                pass

            def complete_response(self, _response):
                pass

            def show_notice(self, text):
                self.notices.append(text)

            def exit(self):
                pass

        app = ApprovalApp()
        prompt = Prompt()

        _run_persistent_interactive(
            app=app,
            prompt_session=prompt,
            user_id="u1",
            session_id="s1",
            system_prompt=None,
            first_message=None,
        )

        self.assertEqual(app.resolve_calls, [("s1", False)])
        self.assertIn("denied the tool bash", app.calls[0].message)
        self.assertIn("■ 已拒绝 · bash", prompt.notices)

    def test_read_interactive_message_uses_prompt_session(self) -> None:
        session = FakePromptSession("hello")

        message = _read_interactive_message(session)

        self.assertEqual(message, "hello")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(
            session.calls[0][0][0],
            [("class:prompt", "❯ ")],
        )
        self.assertEqual(session.calls[0][1]["placeholder"], "Message Navi Agent")

    def test_main_runs_interactive_mode_with_first_message(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
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

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("builtins.input", return_value="y"):
                with patch("navi_agent.cli.main.SmokeWorkflowService") as smoke_cls:
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
                metadata={
                    "operation": "update",
                    "skill_name": "readme-summary",
                    "section": "## Procedure",
                    "append_content": "- Verify README after editing.",
                },
            )
        )
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("builtins.input", return_value="n"):
                with patch("sys.argv", ["navi-agent", "--review-skill"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("operation: update", stdout.getvalue())
        self.assertIn("section: ## Procedure", stdout.getvalue())
        self.assertIn("--- BEGIN PATCH ---", stdout.getvalue())
        self.assertIn("- Verify README after editing.", stdout.getvalue())
        self.assertIn("--- END PATCH ---", stdout.getvalue())
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

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("builtins.input", return_value="y"):
                with patch("navi_agent.cli.main.SmokeWorkflowService") as smoke_cls:
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
        self.assertIs(fake_app.rolled_back_candidate, fake_app.saved_candidates[0])

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

        with patch("navi_agent.cli.main.get_skills_dir", return_value=Path("/tmp/skills")):
            with patch("navi_agent.cli.main.FileSkillStore") as store_cls:
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

        with patch("navi_agent.cli.main.get_skills_dir", return_value=Path("/tmp/skills")):
            with patch("navi_agent.cli.main.get_trace_store_path", return_value=Path("/tmp/traces.jsonl")):
                with patch("navi_agent.cli.main.SkillUsageService") as service_cls:
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

        with patch("navi_agent.cli.main.get_skills_dir", return_value=Path("/tmp/skills")):
            with patch("navi_agent.cli.main.get_trace_store_path", return_value=Path("/tmp/traces.jsonl")):
                with patch("navi_agent.cli.main.SkillCuratorStatusService") as service_cls:
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

    def test_main_archives_unused_agent_skills(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.get_skills_dir", return_value=Path("/tmp/skills")):
            with patch("navi_agent.cli.main.get_trace_store_path", return_value=Path("/tmp/traces.jsonl")):
                with patch("navi_agent.cli.main.SkillCuratorService") as service_cls:
                    service_cls.return_value.archive_unused_agent_created.return_value = SkillCuratorArchiveResult(
                        archived_count=1,
                        archived_names=["readme-summary"],
                        skipped_count=2,
                    )
                    with patch("sys.argv", ["navi-agent", "--skill-curator-archive-unused"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("skills_dir: /tmp/skills", stdout.getvalue())
        self.assertIn("archived_count: 1", stdout.getvalue())
        self.assertIn("skipped_count: 2", stdout.getvalue())
        self.assertIn("archived_skills:", stdout.getvalue())
        self.assertIn("- readme-summary", stdout.getvalue())

    def test_main_prints_background_review_status(self) -> None:
        fake_app = FakeApp()
        fake_app.background_review_status = type(
            "BackgroundReviewStatus",
            (),
            {
                "running": True,
                "pending_count": 1,
                "submitted_count": 3,
                "completed_count": 2,
                "failed_count": 0,
            },
        )()
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--background-review-status"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("background_review: skill", stdout.getvalue())
        self.assertIn("background_review_enabled: true", stdout.getvalue())
        self.assertIn("background_review_running: true", stdout.getvalue())
        self.assertIn("background_review_pending_count: 1", stdout.getvalue())
        self.assertIn("background_review_submitted_count: 3", stdout.getvalue())
        self.assertIn("background_review_completed_count: 2", stdout.getvalue())
        self.assertIn("background_review_failed_count: 0", stdout.getvalue())

    def test_main_prints_runtime_events(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.RuntimeTrajectoryService") as service_cls:
            service_cls.return_value.render.return_value = "runtime_trajectory:\n[1] user.message"
            with patch("navi_agent.cli.main.get_runtime_event_store_path", return_value=Path("/tmp/events.jsonl")):
                with patch("sys.argv", ["navi-agent", "--runtime-events", "--session-id", "s1"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        service_cls.return_value.render.assert_called_once_with(session_id="s1", run_id=None)
        self.assertIn("runtime_event_store_path: /tmp/events.jsonl", stdout.getvalue())
        self.assertIn("runtime_trajectory:", stdout.getvalue())

    def test_main_requires_session_id_for_runtime_events(self) -> None:
        stdout = io.StringIO()

        with patch("sys.argv", ["navi-agent", "--runtime-events"]):
            with redirect_stdout(stdout):
                exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("--runtime-events requires --session-id", stdout.getvalue())

    def test_main_prints_runtime_health(self) -> None:
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.RuntimeHealthService") as service_cls:
            service_cls.return_value.render.return_value = "runtime_health:\nrun_count: 1"
            with patch("navi_agent.cli.main.get_runtime_event_store_path", return_value=Path("/tmp/events.jsonl")):
                with patch("sys.argv", ["navi-agent", "--runtime-health", "--session-id", "s1"]):
                    with redirect_stdout(stdout):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        service_cls.return_value.render.assert_called_once_with(session_id="s1")
        self.assertIn("runtime_event_store_path: /tmp/events.jsonl", stdout.getvalue())
        self.assertIn("runtime_health:", stdout.getvalue())

    def test_main_exports_runtime_tool_use_case(self) -> None:
        stdout = io.StringIO()
        fake_case = object()

        with patch("navi_agent.cli.main.RuntimeTrajectoryService") as trajectory_cls:
            trajectory_cls.return_value.load.return_value = "trajectory"
            with patch("navi_agent.cli.main.build_tool_use_case_from_trajectory", return_value=fake_case):
                with patch("navi_agent.cli.main.render_tool_use_case_jsonl", return_value='{"id":"case-1"}'):
                    with patch("sys.argv", ["navi-agent", "--runtime-export-tool-use-case", "--session-id", "s1"]):
                        with redirect_stdout(stdout):
                            exit_code = main()

        self.assertEqual(exit_code, 0)
        trajectory_cls.return_value.load.assert_called_once_with(session_id="s1", run_id=None)
        self.assertEqual(stdout.getvalue().strip(), '{"id":"case-1"}')

    def test_main_requires_session_id_for_runtime_tool_use_export(self) -> None:
        stdout = io.StringIO()

        with patch("sys.argv", ["navi-agent", "--runtime-export-tool-use-case"]):
            with redirect_stdout(stdout):
                exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("--runtime-export-tool-use-case requires --session-id", stdout.getvalue())

    def test_main_imports_runtime_tool_use_case_candidate(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()
        fake_case = type(
            "FakeCase",
            (),
            {
                "id": "case-1",
                "required_tools": ["read_file"],
                "expected_args": {"read_file": {"path": "README.md"}},
            },
        )()

        with patch("navi_agent.cli.main.RuntimeTrajectoryService") as trajectory_cls:
            trajectory_cls.return_value.load.return_value = type(
                "Trajectory",
                (),
                {"run_id": "r1", "events": []},
            )()
            with patch("navi_agent.cli.main.build_tool_use_case_from_trajectory", return_value=fake_case):
                with patch("navi_agent.cli.main.render_tool_use_case_jsonl", return_value='{"id":"case-1"}'):
                    with patch("navi_agent.cli.main.build_application", return_value=fake_app):
                        with patch("sys.argv", ["navi-agent", "--runtime-import-tool-use-case", "--session-id", "s1"]):
                            with redirect_stdout(stdout):
                                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake_app.saved_candidates), 1)
        candidate = fake_app.saved_candidates[0]
        self.assertEqual(candidate.target, "eval_case")
        self.assertEqual(candidate.metadata["kind"], "tool_use_eval_case")
        self.assertEqual(candidate.metadata["case"], '{"id":"case-1"}')
        self.assertIn("tool_use_case_candidate_written: true", stdout.getvalue())
        self.assertIn("next: uv run navi-agent --review-eval-case", stdout.getvalue())

    def test_main_requires_session_id_for_runtime_tool_use_import(self) -> None:
        stdout = io.StringIO()

        with patch("sys.argv", ["navi-agent", "--runtime-import-tool-use-case"]):
            with redirect_stdout(stdout):
                exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("--runtime-import-tool-use-case requires --session-id", stdout.getvalue())

    def test_main_reviews_and_promotes_tool_use_eval_candidate(self) -> None:
        fake_app = FakeApp()
        fake_app.saved_candidates.append(
            EvolutionCandidate(
                target="eval_case",
                summary="Tool Use Eval case from runtime trajectory",
                rationale="runtime event replay",
                candidate_id="eval-1",
                metadata={
                    "kind": "tool_use_eval_case",
                    "session_id": "s1",
                    "case": (
                        '{"id":"case-1","level":"L1","category":"tool_use.replay",'
                        '"prompt":"读取 README.md","source_inspiration":"runtime-events",'
                        '"required_tools":["read_file"],"forbidden_tools":[],'
                        '"expected_args":{"read_file":{"path":"README.md"}},'
                        '"approval_required_tools":[],"max_iterations":6,'
                        '"grader":"trace_and_answer","expected_outcome":"ok","notes":"n"}'
                    ),
                },
            )
        )
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "tool_use_seed.jsonl"
            with patch("navi_agent.cli.main.build_application", return_value=fake_app):
                with patch("navi_agent.cli.main.get_eval_seed_path", return_value=seed_path):
                    with patch("builtins.input", return_value="y"):
                        with patch("sys.argv", ["navi-agent", "--review-eval-case"]):
                            with redirect_stdout(stdout):
                                exit_code = main()

            cases = ToolUseEvalCaseStore(seed_path).list_cases()

        self.assertEqual(exit_code, 0)
        self.assertEqual(fake_app.saved_candidates[0].status, "accepted")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, "case-1")
        self.assertEqual(cases[0].required_tools, ["read_file"])
        self.assertIn("tool_use_seed_promoted:", stdout.getvalue())
        self.assertIn("candidate_status: accepted", stdout.getvalue())

    def test_main_reviews_non_tool_use_eval_candidate_without_seed_promotion(self) -> None:
        fake_app = FakeApp()
        fake_app.saved_candidates.append(
            EvolutionCandidate(
                target="eval_case",
                summary="Generic eval candidate",
                rationale="runtime signal",
                candidate_id="eval-1",
                metadata={"session_id": "s1"},
            )
        )
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "tool_use_seed.jsonl"
            with patch("navi_agent.cli.main.build_application", return_value=fake_app):
                with patch("navi_agent.cli.main.get_eval_seed_path", return_value=seed_path):
                    with patch("builtins.input", return_value="y"):
                        with patch("sys.argv", ["navi-agent", "--review-eval-case"]):
                            with redirect_stdout(stdout):
                                exit_code = main()

            seed_exists = seed_path.exists()

        self.assertEqual(exit_code, 0)
        self.assertFalse(seed_exists)
        self.assertNotIn("tool_use_seed_promoted:", stdout.getvalue())

    def test_main_prints_disabled_background_review_status(self) -> None:
        fake_app = FakeApp()
        stdout = io.StringIO()

        with patch("navi_agent.cli.main.build_application", return_value=fake_app):
            with patch("sys.argv", ["navi-agent", "--background-review-status"]):
                with redirect_stdout(stdout):
                    exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("background_review_enabled: false", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
