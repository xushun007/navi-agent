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

    def test_can_replace_all_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("x\ny\nx\n", encoding="utf-8")
            tool = PatchTool(root=root)
            result = tool.invoke(path="note.txt", old="x", new="z", replace_all=True)

            self.assertEqual(result.structured_content["replacements"], 2)
            self.assertTrue(result.structured_content["replace_all"])
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "z\ny\nz\n")

    def test_rejects_empty_old_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("abc\n", encoding="utf-8")
            tool = PatchTool(root=root)
            result = tool.invoke(path="note.txt", old="", new="z")

        self.assertEqual(result.status, "error")
        self.assertIn("must not be empty", result.content)
