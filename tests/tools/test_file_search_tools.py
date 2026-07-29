import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navi_agent.tools import GlobTool, GrepTool


class GlobToolTests(unittest.TestCase):
    def test_matches_path_glob_and_sorts_by_modification_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "src"
            source.mkdir()
            older = source / "older.py"
            newer = source / "newer.py"
            older.write_text("older\n", encoding="utf-8")
            newer.write_text("newer\n", encoding="utf-8")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))

            result = GlobTool(root=root).invoke(pattern="src/**/*.py")

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.structured_content["paths"],
            ["src/newer.py", "src/older.py"],
        )
        self.assertFalse(result.structured_content["truncated"])

    def test_rejects_path_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = GlobTool(root=Path(tmpdir)).invoke(
                pattern="*.py",
                path="/",
            )

        self.assertEqual(result.status, "error")
        self.assertIn("outside workspace", result.content)

    def test_reports_missing_ripgrep(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("navi_agent.tools.ripgrep.shutil.which", return_value=None):
                result = GlobTool(root=Path(tmpdir)).invoke(pattern="*.py")

        self.assertEqual(result.status, "error")
        self.assertIn("ripgrep", result.content)

    def test_excludes_worktree_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("", encoding="utf-8")
            worktree = root / ".worktrees" / "copy"
            worktree.mkdir(parents=True)
            (worktree / "copied.py").write_text("", encoding="utf-8")

            result = GlobTool(root=root).invoke(pattern="**/*.py")

        self.assertEqual(result.structured_content["paths"], ["main.py"])


class GrepToolTests(unittest.TestCase):
    def test_finds_regex_matches_with_include_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.py").write_text("alpha1\nbeta\n", encoding="utf-8")
            (root / "b.py").write_text("alpha2\n", encoding="utf-8")
            (root / "ignored.txt").write_text("alpha3\n", encoding="utf-8")

            result = GrepTool(root=root).invoke(
                pattern=r"alpha\d",
                include="*.py",
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.structured_content["match_count"], 2)
        self.assertIn("a.py:1: alpha1", result.content)
        self.assertIn("b.py:1: alpha2", result.content)
        self.assertNotIn("ignored.txt", result.content)

    def test_returns_no_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.txt").write_text("hello\n", encoding="utf-8")

            result = GrepTool(root=root).invoke(pattern="missing")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.content, "No matches found")
        self.assertEqual(result.structured_content["match_count"], 0)

    def test_rejects_invalid_regex(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = GrepTool(root=Path(tmpdir)).invoke(pattern="([")

        self.assertEqual(result.status, "error")
        self.assertIn("ripgrep failed", result.content)

    def test_rejects_path_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = GrepTool(root=Path(tmpdir)).invoke(
                pattern="hello",
                path="/",
            )

        self.assertEqual(result.status, "error")
        self.assertIn("outside workspace", result.content)

    def test_excludes_worktree_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("needle\n", encoding="utf-8")
            worktree = root / ".worktrees" / "copy"
            worktree.mkdir(parents=True)
            (worktree / "copied.py").write_text("needle\n", encoding="utf-8")

            result = GrepTool(root=root).invoke(pattern="needle")

        self.assertEqual(result.structured_content["match_count"], 1)
        self.assertIn("main.py", result.content)
        self.assertNotIn("copied.py", result.content)
