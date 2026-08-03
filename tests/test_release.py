from __future__ import annotations

import tomllib
from pathlib import Path

from scripts.check_release_version import main


def test_release_version_accepts_matching_tag() -> None:
    with Path("pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]

    assert main(f"v{version}") == 0


def test_release_version_rejects_mismatched_tag() -> None:
    assert main("v0.2.0") == 1
