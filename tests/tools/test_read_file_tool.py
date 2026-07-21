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

    def test_reports_missing_path_with_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "notes.txt").write_text("alpha\n", encoding="utf-8")
            tool = ReadFileTool(root=root)
            result = tool.invoke(path="note.txt")

        self.assertEqual(result.status, "error")
        self.assertIn("Did you mean", result.content)
        self.assertIn("notes.txt", result.content)

    def test_marks_truncated_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("a\nb\nc\nd\n", encoding="utf-8")
            tool = ReadFileTool(root=root)
            result = tool.invoke(path="note.txt", start_line=2, line_count=2)

        self.assertTrue(result.structured_content["truncated"])
        self.assertEqual(result.structured_content["next_start_line"], 4)
        self.assertIn("Continue with start_line=4", result.content)

    def test_rejects_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "blob.bin").write_bytes(b"\x00\x01\x02")
            tool = ReadFileTool(root=root)
            result = tool.invoke(path="blob.bin")

        self.assertEqual(result.status, "error")
        self.assertIn("binary file", result.content)

    def test_reads_file_from_added_directory(self) -> None:
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as added:
            added_file = Path(added) / "external.txt"
            added_file.write_text("external\n", encoding="utf-8")
            tool = ReadFileTool(root=Path(workspace), additional_roots=[Path(added)])

            result = tool.invoke(path=str(added_file))

        self.assertEqual(result.status, "success")
        self.assertIn("1: external", result.content)
        self.assertEqual(result.structured_content["path"], str(added_file.resolve()))

    def test_rejects_file_outside_workspace_and_added_directories(self) -> None:
        with (
            tempfile.TemporaryDirectory() as workspace,
            tempfile.TemporaryDirectory() as added,
            tempfile.TemporaryDirectory() as outside,
        ):
            outside_file = Path(outside) / "outside.txt"
            outside_file.write_text("outside\n", encoding="utf-8")
            tool = ReadFileTool(root=Path(workspace), additional_roots=[Path(added)])

            result = tool.invoke(path=str(outside_file))

        self.assertEqual(result.status, "error")
        self.assertIn("outside workspace and added directories", result.content)
