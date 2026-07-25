from __future__ import annotations

import json
import random
import re
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from navi_agent.tooling import ToolArtifact, ToolResult

from ..models import (
    ContextCompactionCheckpoint,
    ConversationState,
    Message,
    ModelResponse,
    RuntimeRunRecord,
    SessionMetadata,
    SessionRecallMessage,
    SessionRecallResult,
    SessionRecallView,
    SessionSummary,
    ToolCall,
)
from .schema import SCHEMA_STATEMENTS


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
                    tool_name,
                    provider,
                    model,
                    token_count,
                    finish_reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    message.role,
                    message.content,
                    message.reasoning_content,
                    message.tool_call_id,
                    self._serialize_tool_calls(message.tool_calls),
                    message.tool_name,
                    message.provider,
                    message.model,
                    message.token_count,
                    message.finish_reason,
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
                SELECT
                    role,
                    content,
                    reasoning_content,
                    tool_call_id,
                    tool_calls,
                    tool_name,
                    provider,
                    model,
                    token_count,
                    finish_reason
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
                tool_name=row["tool_name"],
                provider=row["provider"],
                model=row["model"],
                token_count=row["token_count"],
                finish_reason=row["finish_reason"],
            )
            for row in rows
        ]

    def has_session(self, session_id: str, user_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        return row is not None

    def list_sessions(self, user_id: str, limit: int = 10) -> list[SessionSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, updated_at, message_count
                FROM sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, max(1, limit)),
            ).fetchall()
        return [
            SessionSummary(
                session_id=str(row["id"]),
                updated_at=float(row["updated_at"]),
                message_count=int(row["message_count"]),
            )
            for row in rows
        ]

    def start_run(
        self,
        session: ConversationState,
        run_id: str,
        metadata: SessionMetadata,
    ) -> None:
        def start(connection: sqlite3.Connection) -> None:
            now = time.time()
            connection.execute(
                """
                UPDATE runs
                SET status = 'interrupted',
                    updated_at = ?,
                    completed_at = ?,
                    completion_reason = 'superseded_by_new_run'
                WHERE session_id = ?
                  AND status IN ('started', 'running')
                """,
                (now, now, session.session_id),
            )
            start_boundary = connection.execute(
                """
                SELECT COALESCE(MAX(id), 0) + 1 AS next_message_id
                FROM messages
                """
            ).fetchone()
            connection.execute(
                """
                UPDATE sessions
                SET source = ?,
                    agent_role = ?,
                    parent_session_id = ?,
                    model = COALESCE(?, model),
                    cwd = COALESCE(?, cwd),
                    updated_at = ?,
                    ended_at = NULL,
                    end_reason = NULL
                WHERE id = ?
                """,
                (
                    metadata.source,
                    metadata.agent_role,
                    metadata.parent_session_id,
                    metadata.model,
                    metadata.cwd,
                    time.time(),
                    session.session_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO runs (
                    id,
                    session_id,
                    user_id,
                    source,
                    agent_role,
                    status,
                    model,
                    started_at,
                    updated_at,
                    start_message_id
                )
                VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session.session_id,
                    session.user_id,
                    metadata.source,
                    metadata.agent_role,
                    metadata.model,
                    now,
                    now,
                    int(start_boundary["next_message_id"]),
                ),
            )

        self._execute_write(start)

    def get_run(self, run_id: str) -> RuntimeRunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return RuntimeRunRecord(
            run_id=str(row["id"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            source=str(row["source"]),
            agent_role=str(row["agent_role"]),
            status=str(row["status"]),
            provider=row["provider"],
            model=row["model"],
            started_at=float(row["started_at"]),
            updated_at=float(row["updated_at"]),
            completed_at=(
                float(row["completed_at"]) if row["completed_at"] is not None else None
            ),
            start_message_id=row["start_message_id"],
            end_message_id=row["end_message_id"],
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cache_read_tokens=int(row["cache_read_tokens"]),
            cache_write_tokens=int(row["cache_write_tokens"]),
            reasoning_tokens=int(row["reasoning_tokens"]),
            estimated_cost_usd=row["estimated_cost_usd"],
            trajectory_complete=bool(row["trajectory_complete"]),
            failure_reason=row["failure_reason"],
            completion_reason=row["completion_reason"],
        )

    def start_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        tool_call: ToolCall,
    ) -> None:
        now = time.time()
        self._execute_write(
            lambda connection: connection.execute(
                """
                INSERT INTO tool_executions (
                    run_id,
                    tool_call_id,
                    session_id,
                    tool_name,
                    arguments_json,
                    status,
                    started_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'planned', ?, ?)
                ON CONFLICT(run_id, tool_call_id) DO NOTHING
                """,
                (
                    run_id,
                    tool_call.id,
                    session.session_id,
                    tool_call.name,
                    json.dumps(tool_call.arguments, default=str),
                    now,
                    now,
                ),
            )
        )

    def get_tool_result(self, run_id: str, tool_call_id: str) -> ToolResult | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT result_json
                FROM tool_executions
                WHERE run_id = ?
                  AND tool_call_id = ?
                  AND status = 'completed'
                """,
                (run_id, tool_call_id),
            ).fetchone()
        if row is None or row["result_json"] is None:
            return None
        payload = json.loads(str(row["result_json"]))
        return ToolResult(
            tool_call_id=tool_call_id,
            name=str(payload["name"]),
            content=str(payload["content"]),
            status=str(payload["status"]),
            structured_content=dict(payload.get("structured_content") or {}),
            metadata=dict(payload.get("metadata") or {}),
            artifacts=[
                ToolArtifact(
                    kind=str(item["kind"]),
                    uri=str(item["uri"]),
                    title=item.get("title"),
                    mime_type=item.get("mime_type"),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in payload.get("artifacts") or []
            ],
        )

    def complete_tool_call(
        self,
        session: ConversationState,
        run_id: str,
        result: ToolResult,
    ) -> None:
        now = time.time()
        execution_status = (
            "awaiting_input"
            if result.structured_content.get("interaction_pending") is True
            else "completed"
        )
        payload = {
            "name": result.name,
            "content": result.content,
            "status": result.status,
            "structured_content": result.structured_content,
            "metadata": result.metadata,
            "artifacts": [
                {
                    "kind": artifact.kind,
                    "uri": artifact.uri,
                    "title": artifact.title,
                    "mime_type": artifact.mime_type,
                    "metadata": artifact.metadata,
                }
                for artifact in result.artifacts
            ],
        }
        self._execute_write(
            lambda connection: connection.execute(
                """
                UPDATE tool_executions
                SET status = ?,
                    result_json = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE run_id = ?
                  AND tool_call_id = ?
                  AND session_id = ?
                """,
                (
                    execution_status,
                    json.dumps(payload, default=str),
                    now,
                    now if execution_status == "completed" else None,
                    run_id,
                    result.tool_call_id,
                    session.session_id,
                ),
            )
        )

    def load_compaction_checkpoint(
        self,
        session: ConversationState,
    ) -> ContextCompactionCheckpoint | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    covered_until_message_id,
                    covered_message_count,
                    protected_head_count,
                    source_hash,
                    summary,
                    model,
                    created_at
                FROM context_compaction_checkpoints
                WHERE session_id = ?
                """,
                (session.session_id,),
            ).fetchone()
        if row is None:
            return None
        return ContextCompactionCheckpoint(
            session_id=str(row["session_id"]),
            covered_until_message_id=int(row["covered_until_message_id"]),
            covered_message_count=int(row["covered_message_count"]),
            protected_head_count=int(row["protected_head_count"]),
            source_hash=str(row["source_hash"]),
            summary=str(row["summary"]),
            model=row["model"],
            created_at=float(row["created_at"]),
        )

    def save_compaction_checkpoint(
        self,
        session: ConversationState,
        checkpoint: ContextCompactionCheckpoint,
    ) -> None:
        if checkpoint.session_id != session.session_id:
            raise ValueError("compaction checkpoint session does not match")
        if checkpoint.covered_message_count <= 0:
            raise ValueError("compaction checkpoint must cover at least one message")

        def save(connection: sqlite3.Connection) -> None:
            boundary = connection.execute(
                """
                SELECT id
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT 1 OFFSET ?
                """,
                (session.session_id, checkpoint.covered_message_count - 1),
            ).fetchone()
            if boundary is None:
                raise ValueError("compaction checkpoint exceeds stored message history")
            connection.execute(
                """
                INSERT INTO context_compaction_checkpoints (
                    session_id,
                    covered_until_message_id,
                    covered_message_count,
                    protected_head_count,
                    source_hash,
                    summary,
                    model,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    covered_until_message_id = excluded.covered_until_message_id,
                    covered_message_count = excluded.covered_message_count,
                    protected_head_count = excluded.protected_head_count,
                    source_hash = excluded.source_hash,
                    summary = excluded.summary,
                    model = excluded.model,
                    created_at = excluded.created_at
                """,
                (
                    session.session_id,
                    int(boundary["id"]),
                    checkpoint.covered_message_count,
                    checkpoint.protected_head_count,
                    checkpoint.source_hash,
                    checkpoint.summary,
                    checkpoint.model,
                    checkpoint.created_at or time.time(),
                ),
            )

        self._execute_write(save)

    def record_model_response(
        self,
        session: ConversationState,
        run_id: str,
        response: ModelResponse,
    ) -> None:
        usage = response.usage
        cost = usage.cost_usd
        def record(connection: sqlite3.Connection) -> None:
            now = time.time()
            connection.execute(
                """
                UPDATE sessions
                SET provider = COALESCE(?, provider),
                    model = COALESCE(?, model),
                    input_tokens = input_tokens + ?,
                    output_tokens = output_tokens + ?,
                    cache_read_tokens = cache_read_tokens + ?,
                    cache_write_tokens = cache_write_tokens + ?,
                    reasoning_tokens = reasoning_tokens + ?,
                    estimated_cost_usd = CASE
                        WHEN ? IS NULL THEN estimated_cost_usd
                        ELSE COALESCE(estimated_cost_usd, 0) + ?
                    END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    response.provider,
                    response.model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                    usage.reasoning_tokens,
                    cost,
                    cost,
                    now,
                    session.session_id,
                ),
            )
            connection.execute(
                """
                UPDATE runs
                SET provider = COALESCE(?, provider),
                    model = COALESCE(?, model),
                    input_tokens = input_tokens + ?,
                    output_tokens = output_tokens + ?,
                    cache_read_tokens = cache_read_tokens + ?,
                    cache_write_tokens = cache_write_tokens + ?,
                    reasoning_tokens = reasoning_tokens + ?,
                    estimated_cost_usd = CASE
                        WHEN ? IS NULL THEN estimated_cost_usd
                        ELSE COALESCE(estimated_cost_usd, 0) + ?
                    END,
                    updated_at = ?
                WHERE id = ? AND session_id = ?
                """,
                (
                    response.provider,
                    response.model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                    usage.reasoning_tokens,
                    cost,
                    cost,
                    now,
                    run_id,
                    session.session_id,
                ),
            )

        self._execute_write(record)

    def finalize(
        self,
        session: ConversationState,
        run_id: str,
        *,
        status: str,
        end_reason: str | None = None,
        trajectory_complete: bool = True,
        failure_reason: str | None = None,
    ) -> None:
        completed_at = time.time()
        def complete(connection: sqlite3.Connection) -> None:
            end_boundary = connection.execute(
                """
                SELECT MAX(id) AS end_message_id
                FROM messages
                WHERE session_id = ?
                """,
                (session.session_id,),
            ).fetchone()
            connection.execute(
                """
                UPDATE sessions
                SET updated_at = ?,
                    ended_at = ?,
                    end_reason = ?
                WHERE id = ?
                """,
                (
                    completed_at,
                    completed_at,
                    end_reason or status,
                    session.session_id,
                ),
            )
            connection.execute(
                """
                UPDATE runs
                SET status = ?,
                    updated_at = ?,
                    completed_at = ?,
                    end_message_id = ?,
                    trajectory_complete = ?,
                    failure_reason = ?,
                    completion_reason = ?
                WHERE id = ? AND session_id = ?
                """,
                (
                    _run_status(status),
                    completed_at,
                    completed_at,
                    end_boundary["end_message_id"],
                    int(trajectory_complete),
                    failure_reason,
                    end_reason or status,
                    run_id,
                    session.session_id,
                ),
            )

        self._execute_write(complete)

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

    def discover_sessions(
        self,
        *,
        query: str,
        user_id: str,
        limit: int = 5,
        exclude_session_id: str | None = None,
        window: int = 2,
    ) -> list[SessionRecallResult]:
        normalized_query = query.strip()
        if not normalized_query:
            return []
        table = "messages_fts_trigram" if self._contains_cjk(normalized_query) else "messages_fts"
        match_query = self._build_fts_query(normalized_query, trigram=table.endswith("trigram"))
        if not match_query:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    messages.session_id,
                    messages.id AS message_id,
                    messages.role,
                    messages.content,
                    messages.created_at AS message_created_at,
                    highlight({table}, 0, '[[', ']]') AS highlighted_snippet,
                    sessions.source,
                    sessions.title,
                    sessions.model,
                    sessions.updated_at
                FROM {table}
                JOIN messages ON messages.id = {table}.rowid
                JOIN sessions ON sessions.id = messages.session_id
                WHERE {table} MATCH ?
                  AND sessions.user_id = ?
                  AND messages.active = 1
                  AND sessions.agent_role != 'subagent'
                ORDER BY bm25({table}), messages.created_at DESC
                LIMIT ?
                """,
                (match_query, user_id, max(20, min(limit, 20) * 20)),
            ).fetchall()
            excluded_lineage = (
                self._lineage_root(connection, exclude_session_id)
                if exclude_session_id
                else None
            )
            results = []
            seen_lineages = set()
            for row in rows:
                session_id = str(row["session_id"])
                lineage_id = self._lineage_root(connection, session_id)
                if lineage_id == excluded_lineage or lineage_id in seen_lineages:
                    continue
                seen_lineages.add(lineage_id)
                results.append(
                    self._build_discovery_result(
                        connection,
                        row=row,
                        lineage_id=lineage_id,
                        window=max(0, min(window, 5)),
                    )
                )
                if len(results) >= max(1, min(limit, 20)):
                    break
        return results

    def recall_around(
        self,
        *,
        session_id: str,
        message_id: int,
        user_id: str,
        window: int = 3,
        exclude_session_id: str | None = None,
    ) -> SessionRecallView | None:
        bounded_window = max(0, min(window, 10))
        with self._connect() as connection:
            session_row = self._recallable_session(
                connection,
                session_id=session_id,
                user_id=user_id,
                exclude_session_id=exclude_session_id,
            )
            if session_row is None:
                return None
            anchor = connection.execute(
                "SELECT id FROM messages WHERE id = ? AND session_id = ? AND active = 1",
                (message_id, session_id),
            ).fetchone()
            if anchor is None:
                return None
            before = connection.execute(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE session_id = ? AND active = 1 AND id <= ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, message_id, bounded_window + 1),
            ).fetchall()
            after = connection.execute(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE session_id = ? AND active = 1 AND id > ?
                ORDER BY id
                LIMIT ?
                """,
                (session_id, message_id, bounded_window),
            ).fetchall()
            rows = [*reversed(before), *after]
            first_id = int(rows[0]["id"])
            last_id = int(rows[-1]["id"])
            counts = self._message_counts(connection, session_id, first_id, last_id)
            return self._build_view(
                session_row,
                rows,
                total=counts[0] + len(rows) + counts[1],
                messages_before=counts[0],
                messages_after=counts[1],
                anchor_id=message_id,
            )

    def read_session(
        self,
        *,
        session_id: str,
        user_id: str,
        limit: int = 40,
        exclude_session_id: str | None = None,
    ) -> SessionRecallView | None:
        bounded_limit = max(1, min(limit, 100))
        with self._connect() as connection:
            session_row = self._recallable_session(
                connection,
                session_id=session_id,
                user_id=user_id,
                exclude_session_id=exclude_session_id,
            )
            if session_row is None:
                return None
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ? AND active = 1",
                    (session_id,),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE session_id = ? AND active = 1
                ORDER BY id
                LIMIT ?
                """,
                (session_id, bounded_limit),
            ).fetchall()
            return self._build_view(
                session_row,
                rows,
                total=total,
                messages_before=0,
                messages_after=max(0, total - len(rows)),
            )

    def _build_discovery_result(
        self,
        connection: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        lineage_id: str,
        window: int,
    ) -> SessionRecallResult:
        session_id = str(row["session_id"])
        message_id = int(row["message_id"])
        beginning_rows = self._bookend_rows(connection, session_id, beginning=True)
        ending_rows = self._bookend_rows(connection, session_id, beginning=False)
        before = connection.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE session_id = ? AND active = 1 AND id <= ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, message_id, window + 1),
        ).fetchall()
        after = connection.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE session_id = ? AND active = 1 AND id > ?
            ORDER BY id
            LIMIT ?
            """,
            (session_id, message_id, window),
        ).fetchall()
        window_rows = [*reversed(before), *after]
        counts = self._message_counts(
            connection,
            session_id,
            int(window_rows[0]["id"]),
            int(window_rows[-1]["id"]),
        )
        title = str(row["title"] or "").strip() or self._derive_session_title(
            connection,
            session_id,
        )
        return SessionRecallResult(
            session_id=session_id,
            lineage_id=lineage_id,
            title=title,
            source=str(row["source"]),
            model=row["model"],
            timestamp=float(row["updated_at"]),
            matched_message=SessionRecallMessage(
                id=message_id,
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=float(row["message_created_at"]),
                anchor=True,
            ),
            highlighted_snippet=str(row["highlighted_snippet"]),
            beginning=self._message_records(beginning_rows),
            window=self._message_records(window_rows, anchor_id=message_id),
            ending=self._message_records(ending_rows),
            messages_before=counts[0],
            messages_after=counts[1],
        )

    def _recallable_session(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: str,
        user_id: str,
        exclude_session_id: str | None,
    ) -> sqlite3.Row | None:
        row = connection.execute(
            """
            SELECT id, source, model, title, updated_at
            FROM sessions
            WHERE id = ? AND user_id = ? AND agent_role != 'subagent'
            """,
            (session_id, user_id),
        ).fetchone()
        if row is None:
            return None
        if exclude_session_id and self._lineage_root(
            connection,
            session_id,
        ) == self._lineage_root(connection, exclude_session_id):
            return None
        return row

    @staticmethod
    def _lineage_root(connection: sqlite3.Connection, session_id: str) -> str:
        row = connection.execute(
            """
            WITH RECURSIVE lineage(id, parent_session_id, depth) AS (
                SELECT id, parent_session_id, 0 FROM sessions WHERE id = ?
                UNION ALL
                SELECT parent.id, parent.parent_session_id, lineage.depth + 1
                FROM sessions AS parent
                JOIN lineage ON parent.id = lineage.parent_session_id
                WHERE lineage.depth < 100
            )
            SELECT id FROM lineage ORDER BY depth DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return str(row["id"]) if row is not None else session_id

    @staticmethod
    def _bookend_rows(
        connection: sqlite3.Connection,
        session_id: str,
        *,
        beginning: bool,
    ) -> list[sqlite3.Row]:
        direction = "ASC" if beginning else "DESC"
        rows = connection.execute(
            f"""
            SELECT id, role, content, created_at
            FROM messages
            WHERE session_id = ? AND active = 1
            ORDER BY id {direction}
            LIMIT 2
            """,
            (session_id,),
        ).fetchall()
        return list(rows if beginning else reversed(rows))

    @staticmethod
    def _message_counts(
        connection: sqlite3.Connection,
        session_id: str,
        first_id: int,
        last_id: int,
    ) -> tuple[int, int]:
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN id < ? THEN 1 ELSE 0 END),
                SUM(CASE WHEN id > ? THEN 1 ELSE 0 END)
            FROM messages
            WHERE session_id = ? AND active = 1
            """,
            (first_id, last_id, session_id),
        ).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    @staticmethod
    def _message_records(
        rows: list[sqlite3.Row],
        *,
        anchor_id: int | None = None,
    ) -> list[SessionRecallMessage]:
        return [
            SessionRecallMessage(
                id=int(row["id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=float(row["created_at"]),
                anchor=int(row["id"]) == anchor_id,
            )
            for row in rows
        ]

    def _build_view(
        self,
        session_row: sqlite3.Row,
        rows: list[sqlite3.Row],
        *,
        total: int,
        messages_before: int,
        messages_after: int,
        anchor_id: int | None = None,
    ) -> SessionRecallView:
        session_id = str(session_row["id"])
        title = str(session_row["title"] or "").strip() or self._derive_session_title(
            None,
            session_id,
            rows=rows,
        )
        return SessionRecallView(
            session_id=session_id,
            title=title,
            source=str(session_row["source"]),
            model=session_row["model"],
            timestamp=float(session_row["updated_at"]),
            messages=self._message_records(rows, anchor_id=anchor_id),
            total_message_count=total,
            messages_before=messages_before,
            messages_after=messages_after,
            truncated=messages_before > 0 or messages_after > 0,
        )

    @staticmethod
    def _derive_session_title(
        connection: sqlite3.Connection | None,
        session_id: str,
        *,
        rows: list[sqlite3.Row] | None = None,
    ) -> str:
        if rows is None and connection is not None:
            rows = connection.execute(
                """
                SELECT content FROM messages
                WHERE session_id = ? AND active = 1 AND role = 'user'
                ORDER BY id LIMIT 1
                """,
                (session_id,),
            ).fetchall()
        title_row = next(
            (row for row in rows or [] if "role" not in row.keys() or row["role"] == "user"),
            (rows or [None])[0],
        )
        first = str(title_row["content"]).strip() if title_row is not None else session_id
        return first[:80] + ("…" if len(first) > 80 else "")

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
    def _contains_cjk(value: str) -> bool:
        return any("\u3400" <= character <= "\u9fff" for character in value)

    @staticmethod
    def _build_fts_query(value: str, *, trigram: bool) -> str:
        if trigram:
            return f'"{value.replace(chr(34), chr(34) * 2)}"'
        tokens = re.findall(r"[\w-]+", value, flags=re.UNICODE)
        return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)

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


def _run_status(status: str) -> str:
    return {
        "success": "completed",
        "iteration_limit_exceeded": "failed",
    }.get(status, status)
