import tempfile
import time
import unittest
from pathlib import Path

from navi_agent.runtime import BackgroundTaskManager, ToolContext
from navi_agent.tools import BashTool


class BashToolTests(unittest.TestCase):
    def test_rejects_empty_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir))
            result = tool.invoke(command="   ")

        self.assertEqual(result.status, "error")
        self.assertIn("must not be empty", result.content)

    def test_executes_command_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir), default_timeout_seconds=5)
            result = tool.invoke(command="printf 'hello'")

        self.assertIn("exit_code: 0", result.content)
        self.assertIn("hello", result.content)
        self.assertEqual(result.structured_content["exit_code"], 0)

    def test_rejects_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir))
            parent_dir = str(Path(tmpdir).parent)
            result = tool.invoke(command="pwd", cwd=parent_dir)

        self.assertIn("outside workspace", result.content)
        self.assertEqual(result.status, "error")

    def test_returns_timeout_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir), default_timeout_seconds=1, max_timeout_seconds=1)
            result = tool.invoke(command="python -c 'import time; time.sleep(2)'")

        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.content)
        self.assertTrue(result.structured_content["timed_out"])

    def test_streams_output_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            events = []
            tool = BashTool(root=Path(tmpdir), default_timeout_seconds=5)
            result = tool.invoke(
                context=ToolContext(
                    session_id="s1",
                    user_id="u1",
                    iteration=1,
                    emit_output=events.append,
                ),
                command="printf 'hello\\nworld\\n'",
            )

        self.assertEqual(result.status, "success")
        self.assertTrue(result.structured_content["streaming"])
        self.assertEqual([event["chunk"] for event in events], ["hello\n", "world\n"])

    def test_rejects_background_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir))
            result = tool.invoke(command="sleep 1 &")

        self.assertEqual(result.status, "error")
        self.assertIn("Background commands", result.content)

    def test_submits_background_command_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackgroundTaskManager()
            tool = BashTool(
                root=Path(tmpdir),
                default_timeout_seconds=5,
                background_task_manager=manager,
            )
            started = time.monotonic()
            result = tool.invoke(
                context=ToolContext(session_id="s1", user_id="u1", iteration=1),
                command="python -c 'import time; time.sleep(0.5); print(42)'",
                background=True,
            )

            self.assertLess(time.monotonic() - started, 0.25)
            self.assertEqual(result.status, "success")
            task_id = result.structured_content["task_id"]
            deadline = time.monotonic() + 2
            while manager.get(task_id, session_id="s1", user_id="u1").status not in {
                "succeeded",
                "failed",
            }:
                if time.monotonic() >= deadline:
                    self.fail("background command did not finish")
                time.sleep(0.01)
            task = manager.get(task_id, session_id="s1", user_id="u1")

        self.assertEqual(task.status, "succeeded")
        self.assertIn("42", task.result.content)

    def test_rejects_dangerous_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir))
            result = tool.invoke(command="sudo ls")

        self.assertEqual(result.status, "error")
        self.assertIn("require approval", result.content)

    def test_rejects_command_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tool = BashTool(root=root)
            result = tool.invoke(command="cat ../secret.txt")

        self.assertEqual(result.status, "error")
        self.assertIn("outside workspace", result.content)
