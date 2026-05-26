from __future__ import annotations

from pathlib import Path

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
