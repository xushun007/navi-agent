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
