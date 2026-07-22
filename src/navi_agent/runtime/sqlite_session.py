from __future__ import annotations

import json
import random
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from .models import ConversationState, Message, SessionMetadata, ToolCall
from .sqlite_schema import SCHEMA_STATEMENTS


T = TypeVar("T")


class SQLiteSessionStore:
    _BUSY_TIMEOUT_MS = 250
    _WRITE_MAX_RETRIES = 5
    _WRITE_RETRY_MIN_SECONDS = 0.02
    _WRITE_RETRY_MAX_SECONDS = 0.12

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def load(
        self,
        session_id: str,
        user_id: str,
        metadata: SessionMetadata | None = None,
    ) -> ConversationState:
        metadata = metadata or SessionMetadata()
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
            started_at = time.time()
            self._execute_write(
                lambda write_connection: write_connection.execute(
                    """
                    INSERT OR IGNORE INTO sessions (
                        id,
                        user_id,
                        source,
                        agent_role,
                        parent_session_id,
                        model,
                        cwd,
                        started_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        user_id,
                        metadata.source,
                        metadata.agent_role,
                        metadata.parent_session_id,
                        metadata.model,
                        metadata.cwd,
                        started_at,
                        started_at,
                    ),
                )
            )
            return ConversationState(session_id=session_id, user_id=user_id)

        stored_user_id = str(row["user_id"])
        messages = self.snapshot(ConversationState(session_id=session_id, user_id=stored_user_id))
        return ConversationState(
            session_id=session_id,
            user_id=stored_user_id,
            messages=messages,
        )

    def append(self, session: ConversationState, message: Message) -> None:
        def append_message(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO messages (
                    session_id,
                    role,
                    content,
                    reasoning_content,
                    tool_call_id,
                    tool_calls,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    message.role,
                    message.content,
                    message.reasoning_content,
                    message.tool_call_id,
                    self._serialize_tool_calls(message.tool_calls),
                    time.time(),
                ),
            )
            connection.execute(
                """
                UPDATE sessions
                SET updated_at = ?,
                    message_count = message_count + 1,
                    tool_call_count = tool_call_count + ?
                WHERE id = ?
                """,
                (time.time(), len(message.tool_calls), session.session_id),
            )

        self._execute_write(append_message)

    def snapshot(self, session: ConversationState) -> list[Message]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, reasoning_content, tool_call_id, tool_calls
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
                reasoning_content=row["reasoning_content"],
                tool_call_id=row["tool_call_id"],
                tool_calls=self._deserialize_tool_calls(row["tool_calls"]),
            )
            for row in rows
        ]

    def get_lineage(self, session_id: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE lineage(id, parent_session_id, depth) AS (
                    SELECT id, parent_session_id, 0
                    FROM sessions
                    WHERE id = ?
                    UNION ALL
                    SELECT parent.id, parent.parent_session_id, lineage.depth + 1
                    FROM sessions AS parent
                    JOIN lineage ON parent.id = lineage.parent_session_id
                    WHERE lineage.depth < 100
                )
                SELECT id
                FROM lineage
                ORDER BY depth DESC
                """,
                (session_id,),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
        self._execute_write(self._create_schema)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=self._BUSY_TIMEOUT_MS / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)

    def _execute_write(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(self._WRITE_MAX_RETRIES):
            try:
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    result = operation(connection)
                    connection.commit()
                    return result
            except sqlite3.OperationalError as error:
                if not self._is_lock_error(error):
                    raise
                last_error = error
                if attempt == self._WRITE_MAX_RETRIES - 1:
                    break
                time.sleep(
                    random.uniform(
                        self._WRITE_RETRY_MIN_SECONDS,
                        self._WRITE_RETRY_MAX_SECONDS,
                    )
                )
        raise last_error or sqlite3.OperationalError("database write failed")

    @staticmethod
    def _is_lock_error(error: sqlite3.OperationalError) -> bool:
        error_code = getattr(error, "sqlite_errorcode", None)
        if error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return True
        message = str(error).lower()
        return "locked" in message or "busy" in message

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
