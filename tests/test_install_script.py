from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_installer(
    tmp_path: Path, *, version: str | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv.log"
    _write_executable(bin_dir / "uv", f'#!/bin/sh\nprintf "%s\\n" "$*" > "{log_path}"\n')
    _write_executable(bin_dir / "navi-agent", '#!/bin/sh\necho "navi-agent test-version"\n')

    environment = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }
    if version is not None:
        environment["NAVI_AGENT_VERSION"] = version

    result = subprocess.run(
        ["sh", "scripts/install.sh"],
        check=False,
        capture_output=True,
        cwd=Path(__file__).parents[1],
        env=environment,
        text=True,
    )
    return result, log_path.read_text(encoding="utf-8").strip()


def test_install_script_installs_latest_release(tmp_path: Path) -> None:
    result, uv_arguments = _run_installer(tmp_path)

    assert result.returncode == 0
    assert uv_arguments == "tool install --force navi-agent"
    assert "navi-agent test-version" in result.stdout


def test_install_script_accepts_pinned_version(tmp_path: Path) -> None:
    result, uv_arguments = _run_installer(tmp_path, version="0.1.0")

    assert result.returncode == 0
    assert uv_arguments == "tool install --force navi-agent==0.1.0"
