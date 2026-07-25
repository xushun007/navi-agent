from __future__ import annotations

from typing import Any, Protocol

from navi_agent.runtime import (
    SessionRecallMessage,
    SessionRecallResult,
    SessionRecallView,
)
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


class SessionRecallStore(Protocol):
    def discover_sessions(
        self,
        *,
        query: str,
        user_id: str,
        limit: int = 5,
        exclude_session_id: str | None = None,
        window: int = 2,
    ) -> list[SessionRecallResult]: ...

    def recall_around(
        self,
        *,
        session_id: str,
        message_id: int,
        user_id: str,
        window: int = 3,
        exclude_session_id: str | None = None,
    ) -> SessionRecallView | None: ...

    def read_session(
        self,
        *,
        session_id: str,
        user_id: str,
        limit: int = 40,
        exclude_session_id: str | None = None,
    ) -> SessionRecallView | None: ...


class SessionSearchTool(BaseTool):
    def __init__(self, store: SessionRecallStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return "Discover prior sessions, read a bounded session, or inspect an anchored window."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "session_id": {"type": "string"},
                "around_message_id": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "window": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            "anyOf": [
                {"required": ["query"]},
                {"required": ["session_id", "around_message_id"]},
                {"required": ["session_id"]},
            ],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(name=self.name, content="session_search requires tool context")
        query = str(kwargs.get("query") or "").strip()
        if query:
            results = self._store.discover_sessions(
                query=query,
                user_id=context.user_id,
                limit=int(kwargs.get("limit", 5)),
                exclude_session_id=context.session_id,
                window=int(kwargs.get("window", 2)),
            )
            items = [self._serialize_result(result) for result in results]
            content = "No prior conversation matched." if not items else "\n".join(
                f"- {item['title']} · session={item['session_id']} · "
                f"{item['highlighted_snippet']}"
                for item in items
            )
            return ToolResult.ok(
                name=self.name,
                content=content,
                structured_content={
                    "mode": "discovery",
                    "query": query,
                    "sessions": items,
                    "session_count": len(items),
                },
            )

        session_id = str(kwargs.get("session_id") or "").strip()
        message_id = kwargs.get("around_message_id")
        if not session_id:
            return ToolResult.error(
                name=self.name,
                content="provide query or session_id",
            )
        if isinstance(message_id, int):
            view = self._store.recall_around(
                session_id=session_id,
                message_id=message_id,
                user_id=context.user_id,
                window=int(kwargs.get("window", 3)),
                exclude_session_id=context.session_id,
            )
            mode = "around"
        else:
            view = self._store.read_session(
                session_id=session_id,
                user_id=context.user_id,
                limit=int(kwargs.get("limit", 40)),
                exclude_session_id=context.session_id,
            )
            mode = "read"
        content = "Session or message anchor not found." if view is None else "\n".join(
            f"{'>' if item.anchor else '-'} {item.id} {item.role}: {item.content}"
            for item in view.messages
        )
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "mode": mode,
                "session_id": session_id,
                **({"around_message_id": message_id} if isinstance(message_id, int) else {}),
                **(self._serialize_view(view) if view is not None else {"found": False}),
            },
        )

    @classmethod
    def _serialize_result(cls, result: SessionRecallResult) -> dict[str, object]:
        return {
            "session_id": result.session_id,
            "lineage_id": result.lineage_id,
            "title": result.title,
            "source": result.source,
            "model": result.model,
            "timestamp": result.timestamp,
            "matched_message": cls._serialize_message(result.matched_message),
            "highlighted_snippet": result.highlighted_snippet,
            "beginning": [cls._serialize_message(item) for item in result.beginning],
            "window": [cls._serialize_message(item) for item in result.window],
            "ending": [cls._serialize_message(item) for item in result.ending],
            "messages_before": result.messages_before,
            "messages_after": result.messages_after,
        }

    @classmethod
    def _serialize_view(cls, view: SessionRecallView) -> dict[str, object]:
        return {
            "found": True,
            "title": view.title,
            "source": view.source,
            "model": view.model,
            "timestamp": view.timestamp,
            "messages": [cls._serialize_message(item) for item in view.messages],
            "total_message_count": view.total_message_count,
            "messages_before": view.messages_before,
            "messages_after": view.messages_after,
            "truncated": view.truncated,
        }

    @staticmethod
    def _serialize_message(message: SessionRecallMessage) -> dict[str, object]:
        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
            "anchor": message.anchor,
        }
