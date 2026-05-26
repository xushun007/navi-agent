import tempfile
import unittest
from pathlib import Path

from navi_agent.tools import PatchTool


class PatchToolTests(unittest.TestCase):
    def test_replaces_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("hello world\n", encoding="utf-8")
            tool = PatchTool(root=root)
            result = tool.invoke(path="note.txt", old="world", new="agent")

            self.assertIn("patched", result.content)
            self.assertTrue(result.structured_content["applied"])
            self.assertEqual(result.artifacts[0].kind, "file")
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "hello agent\n")
