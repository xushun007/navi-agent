import tempfile
import unittest
from pathlib import Path

from navi_agent.tools import SearchFilesTool


class SearchFilesToolTests(unittest.TestCase):
    def test_finds_matching_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.txt").write_text("hello world\n", encoding="utf-8")
            (root / "b.py").write_text("print('hello')\n", encoding="utf-8")
            tool = SearchFilesTool(root=root)
            result = tool.invoke(query="hello")

        self.assertIn("a.txt:1: hello world", result.content)
        self.assertIn("b.py:1: print('hello')", result.content)
        self.assertFalse(result.structured_content["truncated"])

    def test_rejects_empty_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tool = SearchFilesTool(root=root)
            result = tool.invoke(query="   ")

        self.assertEqual(result.status, "error")
        self.assertIn("must not be empty", result.content)

    def test_rejects_missing_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tool = SearchFilesTool(root=root)
            result = tool.invoke()

        self.assertEqual(result.status, "error")
        self.assertIn("Missing required argument: query", result.content)

    def test_skips_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.bin").write_bytes(b"hello\x00world")
            (root / "a.txt").write_text("hello text\n", encoding="utf-8")
            tool = SearchFilesTool(root=root)
            result = tool.invoke(query="hello")

        self.assertIn("a.txt:1: hello text", result.content)
        self.assertNotIn("a.bin", result.content)
        self.assertEqual(result.structured_content["match_count"], 1)

    def test_supports_filename_search_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "notes.txt").write_text("alpha\n", encoding="utf-8")
            (root / "todo.md").write_text("beta\n", encoding="utf-8")
            tool = SearchFilesTool(root=root)
            result = tool.invoke(query="note", search_mode="filename")

        self.assertEqual(result.content.strip(), "notes.txt")
        self.assertEqual(result.structured_content["search_mode"], "filename")
        self.assertEqual(result.structured_content["match_count"], 1)

    def test_supports_regex_search_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.txt").write_text("alpha1\nbeta\n", encoding="utf-8")
            (root / "b.txt").write_text("alpha2\n", encoding="utf-8")
            tool = SearchFilesTool(root=root)
            result = tool.invoke(query=r"alpha\d", search_mode="regex")

        self.assertIn("a.txt:1: alpha1", result.content)
        self.assertIn("b.txt:1: alpha2", result.content)
        self.assertEqual(result.structured_content["search_mode"], "regex")
        self.assertEqual(result.structured_content["match_count"], 2)

    def test_rejects_invalid_regex_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tool = SearchFilesTool(root=root)
            result = tool.invoke(query="([", search_mode="regex")

        self.assertEqual(result.status, "error")
        self.assertIn("Invalid regex pattern", result.content)

    def test_rejects_unknown_search_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tool = SearchFilesTool(root=root)
            result = tool.invoke(query="hello", search_mode="unknown")

        self.assertEqual(result.status, "error")
        self.assertIn("Unsupported search_mode", result.content)
