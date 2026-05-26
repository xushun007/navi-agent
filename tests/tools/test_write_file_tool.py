import tempfile
import unittest
from pathlib import Path

from navi_agent.tools import WriteFileTool


class WriteFileToolTests(unittest.TestCase):
    def test_writes_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tool = WriteFileTool(root=root)
            result = tool.invoke(path="note.txt", content="hello\nworld\n")

            self.assertIn("bytes_written", result.content)
            self.assertEqual(result.structured_content["bytes_written"], 12)
            self.assertEqual(result.artifacts[0].title, "note.txt")
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "hello\nworld\n")
