from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


@dataclass(slots=True)
class TodoItem:
    id: str
    content: str
    status: str = "pending"  # pending | in_progress | completed | cancelled
    order: int = 0


class TodoStore:
    """Per-user in-memory todo store."""

    def __init__(self) -> None:
        self._items: dict[str, list[TodoItem]] = {}

    def _list_for_user(self, user_id: str) -> list[TodoItem]:
        return self._items.setdefault(user_id, [])

    def add(self, user_id: str, content: str, status: str = "pending") -> TodoItem:
        items = self._list_for_user(user_id)
        item = TodoItem(
            id=uuid.uuid4().hex[:12],
            content=content,
            status=status,
            order=len(items),
        )
        items.append(item)
        return item

    def list(self, user_id: str, status_filter: str | None = None) -> list[TodoItem]:
        items = self._list_for_user(user_id)
        if status_filter:
            return [i for i in items if i.status == status_filter]
        return sorted(items, key=lambda i: i.order)

    def get(self, user_id: str, item_id: str) -> TodoItem | None:
        for item in self._list_for_user(user_id):
            if item.id == item_id:
                return item
        return None

    def update(
        self,
        user_id: str,
        item_id: str,
        *,
        content: str | None = None,
        status: str | None = None,
    ) -> TodoItem | None:
        item = self.get(user_id, item_id)
        if item is None:
            return None
        if content is not None:
            item.content = content
        if status is not None:
            item.status = status
        return item

    def remove(self, user_id: str, item_id: str) -> bool:
        items = self._list_for_user(user_id)
        for i, item in enumerate(items):
            if item.id == item_id:
                items.pop(i)
                # reindex orders
                for j, remaining in enumerate(items):
                    remaining.order = j
                return True
        return False

    def reorder(self, user_id: str, item_ids: list[str]) -> bool:
        items = self._list_for_user(user_id)
        id_to_item = {i.id: i for i in items}
        # validate all ids exist and no extras
        if len(item_ids) != len(items) or not all(iid in id_to_item for iid in item_ids):
            return False
        ordered = [id_to_item[iid] for iid in item_ids]
        for idx, item in enumerate(ordered):
            item.order = idx
        # mutate the list in-place to preserve reference
        items.clear()
        items.extend(ordered)
        return True


# Global singleton store (same pattern as InMemoryMemoryStore)
_STORE = TodoStore()


class TodoTool(BaseTool):
    """Manage a per-user task list — add, list, update, remove, reorder."""

    def __init__(self, store: TodoStore | None = None) -> None:
        self._store = store or _STORE

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return (
            "Manage your task todo list. "
            "Supports: add (create item), list (show items), "
            "update (change content/status), remove (delete item), "
            "reorder (set item order). "
            "Status values: pending, in_progress, completed, cancelled."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "update", "remove", "reorder"],
                    "description": (
                        "add — create a new todo item (requires content, optional status). "
                        "list — show all items (optional status filter via 'status'). "
                        "update — change content/status of an item (requires id). "
                        "remove — delete an item by id. "
                        "reorder — reorder items by providing an ordered list of ids."
                    ),
                },
                "id": {
                    "type": "string",
                    "description": "Item id. Required for update, remove, reorder.",
                },
                "content": {
                    "type": "string",
                    "description": "Item content/title. Required for add, optional for update.",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                    "description": "Item status. Used as initial status for add, or filter for list, or new status for update.",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of item ids for reorder action.",
                },
            },
            "required": ["action"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(name=self.name, content="todo_error: tool context required")
        user_id = context.user_id
        action = str(kwargs.get("action", "")).strip().lower()

        if action == "add":
            content = str(kwargs.get("content", "")).strip()
            if not content:
                return ToolResult.error(
                    name=self.name,
                    content="todo_error: content is required for add",
                )
            status = str(kwargs.get("status", "pending")).strip().lower()
            if status not in ("pending", "in_progress", "completed", "cancelled"):
                status = "pending"
            item = self._store.add(user_id, content, status)
            return ToolResult.ok(
                name=self.name,
                content=f"todo_added: {item.id}",
                structured_content={
                    "id": item.id,
                    "content": item.content,
                    "status": item.status,
                    "order": item.order,
                },
            )

        if action == "list":
            status_filter = kwargs.get("status")
            if status_filter is not None:
                status_filter = str(status_filter).strip().lower()
                if status_filter not in ("pending", "in_progress", "completed", "cancelled"):
                    status_filter = None
            items = self._store.list(user_id, status_filter)
            if not items:
                return ToolResult.ok(
                    name=self.name,
                    content="todo_empty",
                    structured_content={"items": []},
                )
            lines = []
            serialized = []
            for item in items:
                icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "cancelled": "❌"}.get(
                    item.status, "⬜"
                )
                lines.append(f"{icon} [{item.status}] {item.id}: {item.content}")
                serialized.append({"id": item.id, "content": item.content, "status": item.status, "order": item.order})
            return ToolResult.ok(
                name=self.name,
                content="\n".join(lines),
                structured_content={"items": serialized},
            )

        if action == "update":
            item_id = str(kwargs.get("id", "")).strip()
            if not item_id:
                return ToolResult.error(
                    name=self.name,
                    content="todo_error: id is required for update",
                )
            content = kwargs.get("content")
            if content is not None:
                content = str(content).strip()
            status = kwargs.get("status")
            if status is not None:
                status = str(status).strip().lower()
                if status not in ("pending", "in_progress", "completed", "cancelled"):
                    return ToolResult.error(
                        name=self.name,
                        content=f"todo_error: invalid status '{status}'",
                    )
            if content is None and status is None:
                return ToolResult.error(
                    name=self.name,
                    content="todo_error: provide content and/or status to update",
                )
            updated = self._store.update(user_id, item_id, content=content, status=status)
            if updated is None:
                return ToolResult.error(
                    name=self.name,
                    content=f"todo_error: item not found: {item_id}",
                )
            return ToolResult.ok(
                name=self.name,
                content=f"todo_updated: {updated.id}",
                structured_content={
                    "id": updated.id,
                    "content": updated.content,
                    "status": updated.status,
                    "order": updated.order,
                },
            )

        if action == "remove":
            item_id = str(kwargs.get("id", "")).strip()
            if not item_id:
                return ToolResult.error(
                    name=self.name,
                    content="todo_error: id is required for remove",
                )
            if self._store.remove(user_id, item_id):
                return ToolResult.ok(
                    name=self.name,
                    content=f"todo_removed: {item_id}",
                    structured_content={"id": item_id},
                )
            return ToolResult.error(
                name=self.name,
                content=f"todo_error: item not found: {item_id}",
            )

        if action == "reorder":
            raw_ids = kwargs.get("ids")
            if not raw_ids or not isinstance(raw_ids, list) or len(raw_ids) < 1:
                return ToolResult.error(
                    name=self.name,
                    content="todo_error: ids (array) is required for reorder",
                )
            item_ids = [str(iid).strip() for iid in raw_ids]
            if self._store.reorder(user_id, item_ids):
                return ToolResult.ok(
                    name=self.name,
                    content="todo_reordered",
                    structured_content={"ids": item_ids},
                )
            return ToolResult.error(
                name=self.name,
                content="todo_error: invalid id list for reorder (ids must match all existing items)",
            )

        return ToolResult.error(
            name=self.name,
            content=f"todo_error: unsupported action '{action}'",
        )
