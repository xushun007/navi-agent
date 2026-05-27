import tempfile
import unittest
from pathlib import Path

from navi_agent.tools import BashTool


class BashToolTests(unittest.TestCase):
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
