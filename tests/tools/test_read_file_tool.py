import tempfile
import unittest
from pathlib import Path

from navi_agent.tools import ReadFileTool


class ReadFileToolTests(unittest.TestCase):
    def test_reads_selected_line_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
            tool = ReadFileTool(root=root)
            result = tool.invoke(path="note.txt", start_line=2, line_count=2)

        self.assertIn("2: beta", result.content)
        self.assertIn("3: gamma", result.content)
        self.assertNotIn("1: alpha", result.content)
        self.assertEqual(result.structured_content["line_count"], 2)
        self.assertEqual(result.structured_content["requested_line_count"], 2)
        self.assertEqual(result.artifacts[0].kind, "file")
