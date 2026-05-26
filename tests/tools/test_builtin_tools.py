import tempfile
import unittest
from pathlib import Path

from navi_agent.runtime import ToolContext
from navi_agent.tools import BashTool, ReadFileTool, SearchFilesTool


class BuiltinToolTests(unittest.TestCase):
    def test_read_file_tool_reads_selected_line_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "note.txt"
            path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

            tool = ReadFileTool(root=root)
            result = tool.invoke(path="note.txt", start_line=2, end_line=3)

        self.assertIn("2: beta", result)
        self.assertIn("3: gamma", result)
        self.assertNotIn("1: alpha", result)

    def test_search_files_tool_finds_matching_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.txt").write_text("hello world\n", encoding="utf-8")
            (root / "b.py").write_text("print('hello')\n", encoding="utf-8")

            tool = SearchFilesTool(root=root)
            result = tool.invoke(query="hello")

        self.assertIn("a.txt:1: hello world", result)
        self.assertIn("b.py:1: print('hello')", result)

    def test_bash_tool_executes_command_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir), default_timeout_seconds=5)
            result = tool.invoke(command="printf 'hello'")

        self.assertIn("exit_code: 0", result)
        self.assertIn("hello", result)

    def test_bash_tool_rejects_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(root=Path(tmpdir))
            parent_dir = str(Path(tmpdir).parent)

            result = tool.invoke(command="pwd", cwd=parent_dir)

        self.assertIn("outside workspace", result)
