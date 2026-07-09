import tempfile
import unittest
from pathlib import Path

from navi_agent.tools import CodeExecutorTool


class CodeExecutorToolTests(unittest.TestCase):
    def test_executes_read_patch_run_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.txt"
            path.write_text("hello\n", encoding="utf-8")
            tool = CodeExecutorTool(root=Path(tmpdir), default_timeout_seconds=5)
            result = tool.invoke(
                task="update and verify file",
                steps=[
                    {"action": "read_file", "path": "note.txt"},
                    {"action": "patch", "path": "note.txt", "old": "hello", "new": "hello navi"},
                    {"action": "run", "command": "cat note.txt"},
                ],
            )

        self.assertEqual(result.status, "success")
        self.assertTrue(result.structured_content["success"])
        self.assertEqual(result.structured_content["changed_files"], ["note.txt"])
        self.assertEqual(result.structured_content["commands_run"], ["cat note.txt"])
        self.assertEqual(len(result.structured_content["steps"]), 3)
        self.assertIn("hello navi", result.content)

    def test_writes_file_and_runs_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = CodeExecutorTool(root=Path(tmpdir), default_timeout_seconds=5)
            result = tool.invoke(
                task="create python file",
                steps=[
                    {"action": "write_file", "path": "app.py", "content": "print('ok')\n"},
                    {"action": "run", "command": "python app.py"},
                ],
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.structured_content["changed_files"], ["app.py"])
        self.assertIn("ok", result.content)

    def test_stops_on_failure_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = CodeExecutorTool(root=Path(tmpdir), default_timeout_seconds=5)
            result = tool.invoke(
                task="stop on failure",
                steps=[
                    {"action": "run", "command": "false"},
                    {"action": "run", "command": "printf 'should-not-run'"},
                ],
            )

        self.assertEqual(result.status, "error")
        self.assertFalse(result.structured_content["success"])
        self.assertEqual(len(result.structured_content["steps"]), 1)
        self.assertEqual(result.structured_content["steps"][0]["structured_content"]["exit_code"], 1)

    def test_rejects_unknown_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = CodeExecutorTool(root=Path(tmpdir))
            result = tool.invoke(
                task="unknown action",
                steps=[{"action": "delete_project", "path": "."}],
            )

        self.assertEqual(result.status, "error")
        self.assertIn("Unsupported action", result.content)

    def test_rejects_too_many_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = CodeExecutorTool(root=Path(tmpdir), max_steps=1)
            result = tool.invoke(
                task="too many",
                steps=[
                    {"action": "run", "command": "printf 1"},
                    {"action": "run", "command": "printf 2"},
                ],
            )

        self.assertEqual(result.status, "error")
        self.assertIn("Too many steps", result.content)

    def test_reuses_workspace_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = CodeExecutorTool(root=Path(tmpdir))
            result = tool.invoke(
                task="blocked path",
                steps=[{"action": "run", "command": "cat ../secret.txt"}],
            )

        self.assertEqual(result.status, "error")
        self.assertIn("outside workspace", result.content)
