from __future__ import annotations

from typing import Any, Protocol

from navi_agent.runtime import SessionSearchHit
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


class SessionRecallStore(Protocol):
    def search_sessions(
        self, *, query: str, user_id: str, limit: int = 5
    ) -> list[SessionSearchHit]: ...

    def messages_around(
        self,
        *,
        session_id: str,
        message_id: int,
        user_id: str,
        window: int = 3,
    ) -> list[dict[str, object]]: ...


class SessionSearchTool(BaseTool):
    def __init__(self, store: SessionRecallStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return "Search prior conversations, then inspect messages around a selected match."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "session_id": {"type": "string"},
                "around_message_id": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "window": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            "anyOf": [
                {"required": ["query"]},
                {"required": ["session_id", "around_message_id"]},
            ],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(name=self.name, content="session_search requires tool context")
        query = str(kwargs.get("query") or "").strip()
        if query:
            hits = self._store.search_sessions(
                query=query,
                user_id=context.user_id,
                limit=int(kwargs.get("limit", 5)),
            )
            items = [
                {
                    "session_id": hit.session_id,
                    "message_id": hit.message_id,
                    "role": hit.role,
                    "content": hit.content,
                    "created_at": hit.created_at,
                    "source": hit.source,
                    "title": hit.title,
                }
                for hit in hits
            ]
            content = "No prior conversation matched." if not items else "\n".join(
                f"- session={item['session_id']} message={item['message_id']} "
                f"role={item['role']}: {item['content']}"
                for item in items
            )
            return ToolResult.ok(
                name=self.name,
                content=content,
                structured_content={"mode": "search", "query": query, "matches": items},
            )

        session_id = str(kwargs.get("session_id") or "").strip()
        message_id = kwargs.get("around_message_id")
        if not session_id or not isinstance(message_id, int):
            return ToolResult.error(
                name=self.name,
                content="provide query or session_id with around_message_id",
            )
        messages = self._store.messages_around(
            session_id=session_id,
            message_id=message_id,
            user_id=context.user_id,
            window=int(kwargs.get("window", 3)),
        )
        content = "Message anchor not found." if not messages else "\n".join(
            f"{'>' if item['anchor'] else '-'} {item['id']} {item['role']}: {item['content']}"
            for item in messages
        )
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "mode": "around",
                "session_id": session_id,
                "around_message_id": message_id,
                "messages": messages,
            },
        )
