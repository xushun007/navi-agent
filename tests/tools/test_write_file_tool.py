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
            self.assertFalse(result.structured_content["existed"])
            self.assertEqual(result.artifacts[0].title, "note.txt")
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "hello\nworld\n")

    def test_reports_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("old\n", encoding="utf-8")
            tool = WriteFileTool(root=root)
            result = tool.invoke(path="note.txt", content="new\n")

        self.assertTrue(result.structured_content["existed"])

    def test_rejects_directory_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "docs").mkdir()
            tool = WriteFileTool(root=root)
            result = tool.invoke(path="docs", content="bad")

        self.assertEqual(result.status, "error")
        self.assertIn("directory", result.content)

    def test_rejects_stale_expected_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "note.txt"
            target.write_text("old\n", encoding="utf-8")
            tool = WriteFileTool(root=root)
            result = tool.invoke(
                path="note.txt",
                content="new\n",
                expected_sha256="stale",
            )

        self.assertEqual(result.status, "error")
        self.assertIn("changed since last read", result.content)

    def test_writes_file_to_added_directory(self) -> None:
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as added:
            target = Path(added) / "external.txt"
            tool = WriteFileTool(root=Path(workspace), additional_roots=[Path(added)])

            result = tool.invoke(path=str(target), content="external\n")

            self.assertEqual(result.status, "success")
            self.assertEqual(result.structured_content["path"], str(target.resolve()))
            self.assertEqual(target.read_text(encoding="utf-8"), "external\n")
