from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from .ilink import ILinkMessage


@dataclass(frozen=True, slots=True)
class WeixinInboxRecord:
    account_id: str
    message_id: str
    from_user_id: str
    user_id: str
    session_id: str
    chat_id: str
    chat_type: str
    text: str
    context_token: str | None
    status: str
    last_error: str | None
    created_at: float
    updated_at: float
    completed_at: float | None

    def to_message(self) -> ILinkMessage:
        return ILinkMessage(
            message_id=self.message_id,
            from_user_id=self.from_user_id,
            to_user_id=self.account_id,
            chat_id=self.chat_id,
            chat_type=self.chat_type,
            text=self.text,
            context_token=self.context_token,
        )


@dataclass(frozen=True, slots=True)
class WeixinOutboxRecord:
    id: str
    account_id: str
    delivery_key: str
    kind: str
    source_id: str | None
    to_user_id: str
    text: str
    context_token: str | None
    status: str
    attempt_count: int
    next_attempt_at: float
    last_error: str | None
    created_at: float
    updated_at: float
    delivered_at: float | None


class WeixinDeliveryStore:
    """Small durable inbox/outbox for the single-process Weixin gateway."""

    _BUSY_TIMEOUT_MS = 250

    def __init__(self, db_path: str | Path, *, account_id: str) -> None:
        self._db_path = Path(db_path)
        self._account_id = account_id
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record_inbound(self, message: ILinkMessage, *, now: float | None = None) -> bool:
        if not message.message_id:
            return True
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO weixin_inbox (
                    account_id,
                    message_id,
                    from_user_id,
                    user_id,
                    session_id,
                    chat_id,
                    chat_type,
                    text,
                    context_token,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'received', ?, ?)
                """,
                (
                    self._account_id,
                    message.message_id,
                    message.from_user_id,
                    message.user_id,
                    message.session_id,
                    message.chat_id,
                    message.chat_type,
                    message.text,
                    message.context_token,
                    timestamp,
                    timestamp,
                ),
            )
        return cursor.rowcount == 1

    def get_inbound(self, message_id: str) -> WeixinInboxRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM weixin_inbox
                WHERE account_id = ? AND message_id = ?
                """,
                (self._account_id, message_id),
            ).fetchone()
        return _inbox_record(row) if row is not None else None

    def mark_inbound_running(self, message_id: str, *, now: float | None = None) -> bool:
        return self._set_inbound_status(
            message_id,
            status="running",
            allowed_statuses=("received", "failed"),
            now=now,
        )

    def mark_inbound_completed(self, message_id: str, *, now: float | None = None) -> bool:
        return self._set_inbound_status(
            message_id,
            status="completed",
            allowed_statuses=("running",),
            now=now,
            completed=True,
        )

    def mark_inbound_superseded(self, message_id: str, *, now: float | None = None) -> bool:
        return self._set_inbound_status(
            message_id,
            status="superseded",
            allowed_statuses=("received",),
            now=now,
            completed=True,
        )

    def mark_inbound_failed(
        self,
        message_id: str,
        *,
        error: str,
        now: float | None = None,
    ) -> bool:
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE weixin_inbox
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE account_id = ? AND message_id = ? AND status = 'running'
                """,
                (error, timestamp, self._account_id, message_id),
            )
        return cursor.rowcount == 1

    def recover_inbound(self, *, now: float | None = None) -> list[WeixinInboxRecord]:
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE weixin_inbox
                SET status = 'received', updated_at = ?
                WHERE account_id = ? AND status = 'running'
                """,
                (timestamp, self._account_id),
            )
            rows = connection.execute(
                """
                SELECT *
                FROM weixin_inbox
                WHERE account_id = ? AND status = 'received'
                ORDER BY created_at, message_id
                """,
                (self._account_id,),
            ).fetchall()
        return [_inbox_record(row) for row in rows]

    def enqueue_outbound(
        self,
        *,
        delivery_key: str,
        kind: str,
        to_user_id: str,
        text: str,
        context_token: str | None,
        source_id: str | None = None,
        now: float | None = None,
    ) -> WeixinOutboxRecord:
        if not delivery_key.strip():
            raise ValueError("delivery_key is required")
        if not to_user_id.strip():
            raise ValueError("to_user_id is required")
        if not text.strip():
            raise ValueError("text is required")
        timestamp = now if now is not None else time.time()
        outbound_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO weixin_outbox (
                    id,
                    account_id,
                    delivery_key,
                    kind,
                    source_id,
                    to_user_id,
                    text,
                    context_token,
                    status,
                    next_attempt_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    outbound_id,
                    self._account_id,
                    delivery_key,
                    kind,
                    source_id,
                    to_user_id,
                    text,
                    context_token,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM weixin_outbox
                WHERE account_id = ? AND delivery_key = ?
                """,
                (self._account_id, delivery_key),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to load persisted Weixin outbox record")
        return _outbox_record(row)

    def claim_due_outbound(
        self,
        *,
        limit: int = 20,
        now: float | None = None,
    ) -> list[WeixinOutboxRecord]:
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT id
                FROM weixin_outbox
                WHERE account_id = ?
                  AND status = 'pending'
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at, created_at, id
                LIMIT ?
                """,
                (self._account_id, timestamp, max(1, limit)),
            ).fetchall()
            ids = [str(row["id"]) for row in rows]
            for outbound_id in ids:
                connection.execute(
                    """
                    UPDATE weixin_outbox
                    SET status = 'sending',
                        attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (timestamp, outbound_id),
                )
            claimed = [
                connection.execute(
                    "SELECT * FROM weixin_outbox WHERE id = ?",
                    (outbound_id,),
                ).fetchone()
                for outbound_id in ids
            ]
        return [_outbox_record(row) for row in claimed if row is not None]

    def mark_outbound_delivered(
        self,
        outbound_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE weixin_outbox
                SET status = 'delivered', delivered_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ? AND account_id = ? AND status = 'sending'
                """,
                (timestamp, timestamp, outbound_id, self._account_id),
            )
        return cursor.rowcount == 1

    def mark_outbound_failed(
        self,
        outbound_id: str,
        *,
        error: str,
        retryable: bool,
        max_attempts: int,
        retry_delay_seconds: float,
        now: float | None = None,
    ) -> WeixinOutboxRecord | None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT attempt_count
                FROM weixin_outbox
                WHERE id = ? AND account_id = ? AND status = 'sending'
                """,
                (outbound_id, self._account_id),
            ).fetchone()
            if row is None:
                return None
            exhausted = int(row["attempt_count"]) >= max_attempts
            status = "dead_letter" if exhausted or not retryable else "pending"
            next_attempt_at = timestamp + max(0.0, retry_delay_seconds)
            connection.execute(
                """
                UPDATE weixin_outbox
                SET status = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE id = ? AND account_id = ?
                """,
                (
                    status,
                    next_attempt_at,
                    error,
                    timestamp,
                    outbound_id,
                    self._account_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM weixin_outbox WHERE id = ?",
                (outbound_id,),
            ).fetchone()
        return _outbox_record(updated) if updated is not None else None

    def recover_outbound(self, *, now: float | None = None) -> int:
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE weixin_outbox
                SET status = 'pending', next_attempt_at = ?, updated_at = ?
                WHERE account_id = ? AND status = 'sending'
                """,
                (timestamp, timestamp, self._account_id),
            )
        return cursor.rowcount

    def list_outbound(self, *, status: str | None = None) -> list[WeixinOutboxRecord]:
        query = "SELECT * FROM weixin_outbox WHERE account_id = ?"
        parameters: tuple[object, ...] = (self._account_id,)
        if status is not None:
            query += " AND status = ?"
            parameters += (status,)
        query += " ORDER BY created_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_outbox_record(row) for row in rows]

    def retry_dead_letter(self, outbound_id: str, *, now: float | None = None) -> bool:
        timestamp = now if now is not None else time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE weixin_outbox
                SET status = 'pending', next_attempt_at = ?, last_error = NULL, updated_at = ?
                WHERE id = ? AND account_id = ? AND status = 'dead_letter'
                """,
                (timestamp, timestamp, outbound_id, self._account_id),
            )
        return cursor.rowcount == 1

    def _set_inbound_status(
        self,
        message_id: str,
        *,
        status: str,
        allowed_statuses: tuple[str, ...],
        now: float | None,
        completed: bool = False,
    ) -> bool:
        timestamp = now if now is not None else time.time()
        placeholders = ", ".join("?" for _ in allowed_statuses)
        completed_clause = ", completed_at = ?" if completed else ""
        parameters: list[object] = [status, timestamp]
        if completed:
            parameters.append(timestamp)
        parameters.extend([self._account_id, message_id, *allowed_statuses])
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE weixin_inbox
                SET status = ?, updated_at = ?, last_error = NULL{completed_clause}
                WHERE account_id = ?
                  AND message_id = ?
                  AND status IN ({placeholders})
                """,
                parameters,
            )
        return cursor.rowcount == 1

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS weixin_inbox (
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    from_user_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    chat_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    context_token TEXT,
                    status TEXT NOT NULL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    PRIMARY KEY (account_id, message_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS weixin_outbox (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    delivery_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_id TEXT,
                    to_user_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    context_token TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    delivered_at REAL,
                    UNIQUE (account_id, delivery_key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_weixin_outbox_due
                ON weixin_outbox(account_id, status, next_attempt_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path,
            timeout=self._BUSY_TIMEOUT_MS / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._BUSY_TIMEOUT_MS}")
        return connection


def _inbox_record(row: sqlite3.Row) -> WeixinInboxRecord:
    return WeixinInboxRecord(
        account_id=str(row["account_id"]),
        message_id=str(row["message_id"]),
        from_user_id=str(row["from_user_id"]),
        user_id=str(row["user_id"]),
        session_id=str(row["session_id"]),
        chat_id=str(row["chat_id"]),
        chat_type=str(row["chat_type"]),
        text=str(row["text"]),
        context_token=row["context_token"],
        status=str(row["status"]),
        last_error=row["last_error"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        completed_at=(
            float(row["completed_at"]) if row["completed_at"] is not None else None
        ),
    )


def _outbox_record(row: sqlite3.Row) -> WeixinOutboxRecord:
    return WeixinOutboxRecord(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        delivery_key=str(row["delivery_key"]),
        kind=str(row["kind"]),
        source_id=row["source_id"],
        to_user_id=str(row["to_user_id"]),
        text=str(row["text"]),
        context_token=row["context_token"],
        status=str(row["status"]),
        attempt_count=int(row["attempt_count"]),
        next_attempt_at=float(row["next_attempt_at"]),
        last_error=row["last_error"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        delivered_at=(
            float(row["delivered_at"]) if row["delivered_at"] is not None else None
        ),
    )
