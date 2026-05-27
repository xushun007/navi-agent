from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .base import BaseTool


class WorkspaceTool(BaseTool):
    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path.cwd()).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve_path(self, path: str | None = None) -> Path:
        target = self.root if not path else (self.root / path if not Path(path).is_absolute() else Path(path))
        resolved = target.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path is outside workspace: {resolved}") from exc
        return resolved

    def _is_binary_file(self, path: Path, sample_size: int = 4096) -> bool:
        with path.open("rb") as handle:
            chunk = handle.read(sample_size)
        if not chunk:
            return False
        if b"\x00" in chunk:
            return True
        non_text = sum(
            1
            for byte in chunk
            if byte < 9 or (13 < byte < 32)
        )
        return non_text / len(chunk) > 0.3

    def _find_similar_paths(self, missing_path: str, limit: int = 3) -> list[str]:
        needle = Path(missing_path).name.lower()
        needle_stem = Path(missing_path).stem.lower()
        if not needle:
            return []
        matches: list[str] = []
        for candidate in sorted(self.root.rglob("*")):
            relative = str(candidate.relative_to(self.root))
            name = candidate.name.lower()
            stem = candidate.stem.lower()
            if (
                needle in name
                or name in needle
                or (needle_stem and needle_stem in stem)
                or (needle_stem and stem in needle_stem)
            ):
                matches.append(relative)
                if len(matches) >= limit:
                    break
        return matches

    def _missing_path_error(self, missing_path: str) -> dict[str, Any]:
        suggestions = self._find_similar_paths(missing_path)
        message = f"Path not found: {missing_path}"
        if suggestions:
            message += "\nDid you mean:\n" + "\n".join(suggestions)
        return {
            "content": message,
            "metadata": {"path": missing_path, "suggestions": suggestions},
        }

    def _sha256_text(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
