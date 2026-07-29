from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


DEFAULT_EXCLUDE_GLOBS = (
    "!.git/**",
    "!.worktrees/**",
    "!.venv/**",
    "!node_modules/**",
    "!**/__pycache__/**",
    "!.pytest_cache/**",
)


def default_exclude_arguments() -> list[str]:
    return [
        argument
        for pattern in DEFAULT_EXCLUDE_GLOBS
        for argument in ("--glob", pattern)
    ]


def run_ripgrep(
    arguments: list[str],
    *,
    cwd: Path,
    timeout_seconds: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("rg")
    if executable is None:
        raise FileNotFoundError("ripgrep (rg) is required for file search")
    return subprocess.run(
        [executable, *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
