from __future__ import annotations

from typing import Any

from navi_agent.memory import MemoryStore
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


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
                "action": {"type": "string", "enum": ["add", "list", "update", "remove"]},
                "id": {"type": "string"},
                "kind": {"type": "string", "enum": ["fact", "preference", "task"]},
                "content": {"type": "string"},
            },
            "required": ["action"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            raise ValueError("Memory tool requires tool context")
        action = str(kwargs["action"])
        if action == "add":
            kind = str(kwargs.get("kind", "fact")).strip().lower()
            if kind not in {"fact", "preference", "task"}:
                kind = "fact"
            content = str(kwargs.get("content", "")).strip()
            if not content:
                return ToolResult.error(
                    name=self.name,
                    content="memory_error: content is required for add",
                )
            record = self._memory_store.add_for_user(context.user_id, content, kind=kind)
            return ToolResult.ok(
                name=self.name,
                content="memory_stored",
                structured_content={"user_id": record.user_id, "kind": record.kind, "content": record.content},
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
                structured_content={
                    "records": [
                        {"id": record.id, "kind": record.kind, "content": record.content} for record in records
                    ]
                },
            )
        if action == "update":
            record_id = str(kwargs.get("id", "")).strip()
            content = str(kwargs.get("content", "")).strip()
            if not record_id:
                return ToolResult.error(name=self.name, content="memory_error: id is required for update")
            if not content:
                return ToolResult.error(name=self.name, content="memory_error: content is required for update")
            record = self._memory_store.update_for_user(context.user_id, record_id, content)
            if record is None:
                return ToolResult.error(
                    name=self.name,
                    content=f"memory_error: item not found: {record_id}",
                )
            return ToolResult.ok(
                name=self.name,
                content="memory_updated",
                structured_content={"id": record.id, "kind": record.kind, "content": record.content},
            )
        if action == "remove":
            record_id = str(kwargs.get("id", "")).strip()
            if not record_id:
                return ToolResult.error(name=self.name, content="memory_error: id is required for remove")
            if not self._memory_store.remove_for_user(context.user_id, record_id):
                return ToolResult.error(
                    name=self.name,
                    content=f"memory_error: item not found: {record_id}",
                )
            return ToolResult.ok(
                name=self.name,
                content="memory_removed",
                structured_content={"id": record_id},
            )
        return ToolResult.error(
            name=self.name,
            content=f"memory_error: unsupported action '{action}'",
        )
