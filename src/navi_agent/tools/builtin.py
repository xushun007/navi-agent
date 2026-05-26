from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

from navi_agent.memory import MemoryStore
from navi_agent.runtime.models import ToolArtifact, ToolContext, ToolResult

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


class BashTool(WorkspaceTool):
    def __init__(self, root: Path | None = None, default_timeout_seconds: int = 20) -> None:
        super().__init__(root=root)
        self._default_timeout_seconds = default_timeout_seconds

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a shell command inside the workspace."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "required": ["command"],
        }

    def invoke(
        self,
        context: ToolContext | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        command = str(kwargs["command"])
        timeout_seconds = int(kwargs.get("timeout_seconds", self._default_timeout_seconds))
        timeout_seconds = max(1, min(timeout_seconds, 60))
        try:
            cwd = self._resolve_path(kwargs.get("cwd"))
        except ValueError as exc:
            return ToolResult.error(
                name=self.name,
                content=str(exc),
                metadata={"cwd": kwargs.get("cwd")},
            )

        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        parts = [f"exit_code: {completed.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        return ToolResult.ok(
            name=self.name,
            content="\n".join(parts),
            structured_content={
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            metadata={"cwd": str(cwd), "timeout_seconds": timeout_seconds},
        ) if completed.returncode == 0 else ToolResult.error(
            name=self.name,
            content="\n".join(parts),
            structured_content={
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            metadata={"cwd": str(cwd), "timeout_seconds": timeout_seconds},
        )


class ReadFileTool(WorkspaceTool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read a text file from the workspace."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        resolved = self._resolve_path(str(kwargs["path"]))
        lines = resolved.read_text(encoding="utf-8").splitlines()
        start_line = max(1, int(kwargs.get("start_line", 1)))
        end_line = int(kwargs.get("end_line", len(lines)))
        selected = lines[start_line - 1 : end_line]
        content = "\n".join(
            f"{line_number}: {content}"
            for line_number, content in enumerate(selected, start=start_line)
        )
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "path": str(resolved.relative_to(self.root)),
                "start_line": start_line,
                "end_line": end_line,
                "line_count": len(selected),
            },
            artifacts=[
                ToolArtifact(
                    kind="file",
                    uri=str(resolved),
                    title=str(resolved.relative_to(self.root)),
                    mime_type="text/plain",
                )
            ],
        )


class SearchFilesTool(WorkspaceTool):
    def __init__(self, root: Path | None = None, max_matches: int = 50) -> None:
        super().__init__(root=root)
        self._max_matches = max_matches

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return "Search text across workspace files."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string"},
            },
            "required": ["query"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        query = str(kwargs["query"])
        base_path = self._resolve_path(kwargs.get("path"))
        pattern = str(kwargs.get("glob", "*"))
        matches: list[str] = []

        for path in sorted(base_path.rglob("*")):
            if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            rel_path = path.relative_to(self.root)
            for line_number, line in enumerate(lines, start=1):
                if query in line:
                    matches.append(f"{rel_path}:{line_number}: {line}")
                    if len(matches) >= self._max_matches:
                        return ToolResult.ok(
                            name=self.name,
                            content="\n".join(matches),
                            structured_content={"matches": matches, "truncated": True},
                        )
        return ToolResult.ok(
            name=self.name,
            content="\n".join(matches),
            structured_content={"matches": matches, "truncated": False},
        )


class WriteFileTool(WorkspaceTool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write a text file inside the workspace."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        resolved = self._resolve_path(str(kwargs["path"]))
        resolved.parent.mkdir(parents=True, exist_ok=True)
        content = str(kwargs["content"])
        resolved.write_text(content, encoding="utf-8")
        bytes_written = len(content.encode("utf-8"))
        return ToolResult.ok(
            name=self.name,
            content=f"bytes_written: {bytes_written}",
            structured_content={
                "path": str(resolved.relative_to(self.root)),
                "bytes_written": bytes_written,
            },
            artifacts=[
                ToolArtifact(
                    kind="file",
                    uri=str(resolved),
                    title=str(resolved.relative_to(self.root)),
                    mime_type="text/plain",
                )
            ],
        )


class PatchTool(WorkspaceTool):
    @property
    def name(self) -> str:
        return "patch"

    @property
    def description(self) -> str:
        return "Apply a simple text replacement patch to a file."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        resolved = self._resolve_path(str(kwargs["path"]))
        current = resolved.read_text(encoding="utf-8")
        old = str(kwargs["old"])
        if old not in current:
            return ToolResult.error(
                name=self.name,
                content="patch_failed: target text not found",
                structured_content={"path": str(resolved.relative_to(self.root)), "applied": False},
            )
        updated = current.replace(old, str(kwargs["new"]), 1)
        resolved.write_text(updated, encoding="utf-8")
        return ToolResult.ok(
            name=self.name,
            content="patched: 1 replacement",
            structured_content={"path": str(resolved.relative_to(self.root)), "applied": True, "replacements": 1},
            artifacts=[
                ToolArtifact(
                    kind="file",
                    uri=str(resolved),
                    title=str(resolved.relative_to(self.root)),
                    mime_type="text/plain",
                )
            ],
        )


class MemoryTool(BaseTool):
    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory_store = memory_store

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return "Store and recall durable user memory."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list"]},
                "content": {"type": "string"},
            },
            "required": ["action"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            raise ValueError("Memory tool requires tool context")
        action = str(kwargs["action"])
        if action == "add":
            content = str(kwargs.get("content", "")).strip()
            if not content:
                return ToolResult.error(
                    name=self.name,
                    content="memory_error: content is required for add",
                )
            record = self._memory_store.add_for_user(context.user_id, content)
            return ToolResult.ok(
                name=self.name,
                content="memory_stored",
                structured_content={"user_id": record.user_id, "content": record.content},
            )
        if action == "list":
            records = self._memory_store.list_for_user(context.user_id)
            if not records:
                return ToolResult.ok(
                    name=self.name,
                    content="memory_empty",
                    structured_content={"records": []},
                )
            return ToolResult.ok(
                name=self.name,
                content="\n".join(f"- {record.content}" for record in records),
                structured_content={"records": [record.content for record in records]},
            )
        return ToolResult.error(
            name=self.name,
            content=f"memory_error: unsupported action '{action}'",
        )
