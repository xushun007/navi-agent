import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from navi_agent.runtime import Message, SessionMetadata, SQLiteSessionStore, ToolCall
from navi_agent.runtime.models import ConversationState


class SQLiteSessionStoreTests(unittest.TestCase):
    def test_load_creates_session_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")

            session = store.load(session_id="s1", user_id="u1")

            self.assertEqual(session.session_id, "s1")
            self.assertEqual(session.user_id, "u1")
            self.assertEqual(session.messages, [])

    def test_append_and_snapshot_round_trip_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            session = store.load(session_id="s1", user_id="u1")
            store.append(session, Message(role="user", content="hello"))
            store.append(
                session,
                Message(
                    role="assistant",
                    content="calling tool",
                    reasoning_content="need the echo tool",
                    tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "x"})],
                ),
            )
            snapshot = store.snapshot(session)

            self.assertEqual([message.role for message in snapshot], ["user", "assistant"])
            self.assertEqual(snapshot[0].content, "hello")
            self.assertEqual(snapshot[1].tool_calls[0].name, "echo")
            self.assertEqual(snapshot[1].tool_calls[0].arguments, {"value": "x"})
            self.assertEqual(snapshot[1].reasoning_content, "need the echo tool")

    def test_load_restores_existing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            session = store.load(session_id="s1", user_id="u1")
            store.append(session, Message(role="user", content="hello"))

            restored = store.load(session_id="s1", user_id="u1")

            self.assertEqual(len(restored.messages), 1)
            self.assertEqual(restored.messages[0].content, "hello")

    def test_store_uses_wal_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            SQLiteSessionStore(db_path)

            with sqlite3.connect(db_path) as connection:
                mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

            self.assertEqual(mode.lower(), "wal")

    def test_store_creates_target_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"

            SQLiteSessionStore(db_path)

            with sqlite3.connect(db_path) as connection:
                session_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(sessions)")
                }
                message_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(messages)")
                }
            self.assertTrue(
                {
                    "source",
                    "agent_role",
                    "parent_session_id",
                    "model",
                    "updated_at",
                    "message_count",
                    "input_tokens",
                    "estimated_cost_usd",
                    "metadata",
                }.issubset(session_columns)
            )
            self.assertTrue(
                {
                    "tool_name",
                    "reasoning_content",
                    "model",
                    "token_count",
                    "source_message_id",
                    "active",
                    "metadata",
                }.issubset(message_columns)
            )

    def test_append_waits_for_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            store = SQLiteSessionStore(db_path)
            session = store.load(session_id="s1", user_id="u1")
            blocker = sqlite3.connect(db_path)
            blocker.execute("BEGIN IMMEDIATE")
            errors = []

            def append_message() -> None:
                try:
                    store.append(session, Message(role="user", content="after lock"))
                except Exception as error:  # pragma: no cover - asserted below
                    errors.append(error)

            worker = threading.Thread(target=append_message)
            worker.start()
            time.sleep(0.35)
            blocker.commit()
            blocker.close()
            worker.join(timeout=2)

            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(store.snapshot(session)[0].content, "after lock")

    def test_store_persists_session_metadata_and_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            store = SQLiteSessionStore(db_path)
            parent = store.load(
                session_id="parent",
                user_id="u1",
                metadata=SessionMetadata(
                    source="weixin",
                    model="deepseek-v4-pro",
                    cwd="/workspace",
                ),
            )
            child = store.load(
                session_id="child",
                user_id="u1",
                metadata=SessionMetadata(
                    source="subagent",
                    agent_role="subagent",
                    parent_session_id=parent.session_id,
                    model="deepseek-v4-pro",
                    cwd="/workspace",
                ),
            )
            store.append(child, Message(role="assistant", content="done"))

            with sqlite3.connect(db_path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    "SELECT * FROM sessions WHERE id = 'child'"
                ).fetchone()

            self.assertEqual(row["source"], "subagent")
            self.assertEqual(row["agent_role"], "subagent")
            self.assertEqual(row["parent_session_id"], "parent")
            self.assertEqual(row["model"], "deepseek-v4-pro")
            self.assertEqual(row["cwd"], "/workspace")
            self.assertEqual(row["message_count"], 1)
            self.assertEqual(store.get_lineage("child"), ["parent", "child"])

    def test_store_searches_english_and_chinese_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            first = store.load("s1", "u1")
            second = store.load("s2", "u1")
            other_user = store.load("s3", "u2")
            store.append(first, Message(role="user", content="debug sqlite lock contention"))
            store.append(first, Message(role="assistant", content="use bounded retry"))
            store.append(second, Message(role="user", content="我喜欢简洁直接的技术回答"))
            store.append(other_user, Message(role="user", content="debug sqlite lock contention"))

            english_hits = store.search_sessions(query="sqlite lock", user_id="u1")
            chinese_hits = store.search_sessions(query="简洁直接", user_id="u1")

            self.assertEqual([hit.session_id for hit in english_hits], ["s1"])
            self.assertEqual([hit.session_id for hit in chinese_hits], ["s2"])
            messages = store.messages_around(
                session_id="s1",
                message_id=english_hits[0].message_id,
                user_id="u1",
                window=1,
            )
            self.assertEqual([item["content"] for item in messages], [
                "debug sqlite lock contention",
                "use bounded retry",
            ])
            self.assertTrue(messages[0]["anchor"])


if __name__ == "__main__":
    unittest.main()
