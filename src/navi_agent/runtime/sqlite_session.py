from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import ConversationState, Message, ToolCall


class SQLiteSessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def load(self, session_id: str, user_id: str) -> ConversationState:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO sessions (id, user_id, started_at)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, user_id, time.time()),
                )
                connection.commit()
                return ConversationState(session_id=session_id, user_id=user_id)

            stored_user_id = str(row["user_id"])
            messages = self.snapshot(ConversationState(session_id=session_id, user_id=stored_user_id))
            return ConversationState(
                session_id=session_id,
                user_id=stored_user_id,
                messages=messages,
            )

    def append(self, session: ConversationState, message: Message) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    session_id,
                    role,
                    content,
                    tool_call_id,
                    tool_calls,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    message.role,
                    message.content,
                    message.tool_call_id,
                    self._serialize_tool_calls(message.tool_calls),
                    time.time(),
                ),
            )
            connection.commit()

    def snapshot(self, session: ConversationState) -> list[Message]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, tool_call_id, tool_calls
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session.session_id,),
            ).fetchall()

        return [
            Message(
                role=str(row["role"]),
                content=str(row["content"] or ""),
                tool_call_id=row["tool_call_id"],
                tool_calls=self._deserialize_tool_calls(row["tool_calls"]),
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    started_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_call_id TEXT,
                    tool_calls TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id)
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _serialize_tool_calls(tool_calls: list[ToolCall]) -> str:
        return json.dumps(
            [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
                for tool_call in tool_calls
            ]
        )

    @staticmethod
    def _deserialize_tool_calls(payload: str | None) -> list[ToolCall]:
        if not payload:
            return []
        raw_items = json.loads(payload)
        return [
            ToolCall(
                id=str(item["id"]),
                name=str(item["name"]),
                arguments=dict(item.get("arguments", {})),
            )
            for item in raw_items
        ]
