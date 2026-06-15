import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from navi_agent.cli import _run_interactive, build_parser, main
from navi_agent.runtime import CliApprovalProvider, RuntimeResult


class FakeApp:
    def __init__(self) -> None:
        self.calls = []

    def handle(self, request):
        self.calls.append(request)
        return RuntimeResult(
            session_id=request.session_id or "generated",
            status="success",
            final_response="done",
        )


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
                "results": [
                    RuntimeResult(session_id="wf-1", status="success", final_response="first"),
                    RuntimeResult(session_id="wf-1", status="success", final_response="second"),
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
        self.assertIn("second", stdout.getvalue())
        run_smoke_workflow_mock.assert_called_once()

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
