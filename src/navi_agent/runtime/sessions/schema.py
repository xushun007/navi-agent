from __future__ import annotations

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'console',
        agent_role TEXT NOT NULL DEFAULT 'primary',
        parent_session_id TEXT REFERENCES sessions(id),
        provider TEXT,
        model TEXT,
        cwd TEXT,
        title TEXT,
        started_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        ended_at REAL,
        end_reason TEXT,
        message_count INTEGER NOT NULL DEFAULT 0,
        tool_call_count INTEGER NOT NULL DEFAULT 0,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        cache_write_tokens INTEGER NOT NULL DEFAULT 0,
        reasoning_tokens INTEGER NOT NULL DEFAULT 0,
        estimated_cost_usd REAL,
        metadata TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        reasoning_content TEXT,
        tool_call_id TEXT,
        tool_calls TEXT,
        tool_name TEXT,
        provider TEXT,
        model TEXT,
        token_count INTEGER,
        finish_reason TEXT,
        source_message_id TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL,
        source TEXT NOT NULL,
        agent_role TEXT NOT NULL,
        status TEXT NOT NULL,
        provider TEXT,
        model TEXT,
        started_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        completed_at REAL,
        start_message_id INTEGER,
        end_message_id INTEGER,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        cache_write_tokens INTEGER NOT NULL DEFAULT 0,
        reasoning_tokens INTEGER NOT NULL DEFAULT 0,
        estimated_cost_usd REAL,
        trajectory_complete INTEGER NOT NULL DEFAULT 1,
        failure_reason TEXT,
        completion_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_compaction_checkpoints (
        session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
        covered_until_message_id INTEGER NOT NULL REFERENCES messages(id),
        covered_message_count INTEGER NOT NULL,
        protected_head_count INTEGER NOT NULL,
        source_hash TEXT NOT NULL,
        summary TEXT NOT NULL,
        model TEXT,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_executions (
        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        tool_call_id TEXT NOT NULL,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        tool_name TEXT NOT NULL,
        arguments_json TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT,
        started_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        completed_at REAL,
        PRIMARY KEY (run_id, tool_call_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id, id)
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_session_active ON messages(session_id, active, id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_source_id ON messages(source_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_source_started ON sessions(source, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_session_started ON runs(session_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status_updated ON runs(status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_tool_executions_session ON tool_executions(session_id, started_at)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(content, tokenize='trigram')",
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
        INSERT INTO messages_fts_trigram(rowid, content) VALUES (new.id, new.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
        DELETE FROM messages_fts WHERE rowid = old.id;
        DELETE FROM messages_fts_trigram WHERE rowid = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE OF content ON messages BEGIN
        DELETE FROM messages_fts WHERE rowid = old.id;
        DELETE FROM messages_fts_trigram WHERE rowid = old.id;
        INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
        INSERT INTO messages_fts_trigram(rowid, content) VALUES (new.id, new.content);
    END
    """,
)
