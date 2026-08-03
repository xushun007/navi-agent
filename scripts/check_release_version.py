from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main(tag: str) -> int:
    with Path("pyproject.toml").open("rb") as file:
        project_version = tomllib.load(file)["project"]["version"]

    release_version = tag.removeprefix("v")
    if release_version != project_version:
        print(
            f"Release tag {tag!r} does not match project version {project_version!r}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
