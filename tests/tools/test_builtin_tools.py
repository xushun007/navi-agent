import tempfile
import unittest
from pathlib import Path

from navi_agent.runtime import ToolContext
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.tools import BashTool, ReadFileTool, SearchFilesTool
from navi_agent.tools.builtin import MemoryTool, PatchTool, WriteFileTool


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

    def test_write_file_tool_writes_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tool = WriteFileTool(root=root)

            result = tool.invoke(path="note.txt", content="hello\nworld\n")

            self.assertIn("bytes_written", result)
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "hello\nworld\n")

    def test_patch_tool_replaces_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("hello world\n", encoding="utf-8")
            tool = PatchTool(root=root)

            result = tool.invoke(path="note.txt", old="world", new="agent")

            self.assertIn("patched", result)
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "hello agent\n")

    def test_memory_tool_adds_and_lists_records(self) -> None:
        store = InMemoryMemoryStore()
        tool = MemoryTool(memory_store=store)

        add_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=1),
            action="add",
            content="Likes short answers",
        )
        list_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=2),
            action="list",
        )

        self.assertIn("stored", add_result)
        self.assertIn("Likes short answers", list_result)
