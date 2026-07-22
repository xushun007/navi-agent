from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                started_at REAL NOT NULL
            )
            """,
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
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id)
            """,
        ),
    ),
    Migration(
        version=2,
        statements=(
            "ALTER TABLE sessions ADD COLUMN source TEXT NOT NULL DEFAULT 'console'",
            "ALTER TABLE sessions ADD COLUMN agent_role TEXT NOT NULL DEFAULT 'primary'",
            "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT REFERENCES sessions(id)",
            "ALTER TABLE sessions ADD COLUMN provider TEXT",
            "ALTER TABLE sessions ADD COLUMN model TEXT",
            "ALTER TABLE sessions ADD COLUMN cwd TEXT",
            "ALTER TABLE sessions ADD COLUMN title TEXT",
            "ALTER TABLE sessions ADD COLUMN updated_at REAL",
            "ALTER TABLE sessions ADD COLUMN ended_at REAL",
            "ALTER TABLE sessions ADD COLUMN end_reason TEXT",
            "ALTER TABLE sessions ADD COLUMN message_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN tool_call_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN cache_write_tokens INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN reasoning_tokens INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN estimated_cost_usd REAL",
            "ALTER TABLE sessions ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'",
            "UPDATE sessions SET updated_at = started_at WHERE updated_at IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_sessions_source_started ON sessions(source, started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id)",
            "ALTER TABLE messages ADD COLUMN tool_name TEXT",
            "ALTER TABLE messages ADD COLUMN reasoning_content TEXT",
            "ALTER TABLE messages ADD COLUMN provider TEXT",
            "ALTER TABLE messages ADD COLUMN model TEXT",
            "ALTER TABLE messages ADD COLUMN token_count INTEGER",
            "ALTER TABLE messages ADD COLUMN finish_reason TEXT",
            "ALTER TABLE messages ADD COLUMN source_message_id TEXT",
            "ALTER TABLE messages ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'",
            "CREATE INDEX IF NOT EXISTS idx_messages_session_active ON messages(session_id, active, id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_source_id ON messages(source_message_id)",
        ),
    ),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version
