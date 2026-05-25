import sqlite3
import tempfile
import unittest
from pathlib import Path

from navi_agent.runtime import Message, SQLiteSessionStore, ToolCall
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
                    tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "x"})],
                ),
            )
            snapshot = store.snapshot(session)

            self.assertEqual([message.role for message in snapshot], ["user", "assistant"])
            self.assertEqual(snapshot[0].content, "hello")
            self.assertEqual(snapshot[1].tool_calls[0].name, "echo")
            self.assertEqual(snapshot[1].tool_calls[0].arguments, {"value": "x"})

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


if __name__ == "__main__":
    unittest.main()
