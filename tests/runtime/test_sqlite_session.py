import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from navi_agent.runtime import (
    ContextCompactionCheckpoint,
    Message,
    ModelResponse,
    ModelUsage,
    SessionMetadata,
    SQLiteSessionStore,
    ToolArtifact,
    ToolCall,
    ToolResult,
)
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
                checkpoint_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(context_compaction_checkpoints)"
                    )
                }
                tool_execution_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(tool_executions)")
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
            self.assertTrue(
                {
                    "session_id",
                    "covered_until_message_id",
                    "covered_message_count",
                    "protected_head_count",
                    "source_hash",
                    "summary",
                    "model",
                }.issubset(checkpoint_columns)
            )
            self.assertTrue(
                {
                    "run_id",
                    "tool_call_id",
                    "session_id",
                    "tool_name",
                    "arguments_json",
                    "status",
                    "result_json",
                }.issubset(tool_execution_columns)
            )

    def test_tool_execution_checkpoint_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            store = SQLiteSessionStore(db_path)
            session = store.load(session_id="s1", user_id="u1")
            store.start_run(session, "run-1", SessionMetadata())
            call = ToolCall(id="tc1", name="write_file", arguments={"path": "a.txt"})
            result = ToolResult.ok(
                name="write_file",
                content="written",
                structured_content={"path": "a.txt"},
                metadata={"duration_ms": 4},
                artifacts=[ToolArtifact(kind="file", uri="a.txt")],
            ).bind("tc1")

            store.start_tool_call(session, "run-1", call)
            store.complete_tool_call(session, "run-1", result)

            restored = SQLiteSessionStore(db_path).get_tool_result("run-1", "tc1")
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.name, "write_file")
            self.assertEqual(restored.content, "written")
            self.assertEqual(restored.structured_content, {"path": "a.txt"})
            self.assertEqual(restored.metadata, {"duration_ms": 4})
            self.assertEqual(restored.artifacts[0].uri, "a.txt")

    def test_compaction_checkpoint_round_trip_keeps_raw_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            session = store.load(session_id="s1", user_id="u1")
            for role, content in [
                ("system", "system"),
                ("user", "initial"),
                ("assistant", "large historical result"),
                ("user", "latest"),
            ]:
                store.append(session, Message(role=role, content=content))

            store.save_compaction_checkpoint(
                session,
                ContextCompactionCheckpoint(
                    session_id="s1",
                    covered_message_count=3,
                    protected_head_count=2,
                    source_hash="source-hash",
                    summary="[Context Summary]\ncompleted earlier work",
                    model="test-model",
                ),
            )

            checkpoint = store.load_compaction_checkpoint(session)
            snapshot = store.snapshot(session)

            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint.covered_message_count, 3)
            self.assertEqual(checkpoint.protected_head_count, 2)
            self.assertEqual(checkpoint.summary, "[Context Summary]\ncompleted earlier work")
            self.assertEqual(checkpoint.model, "test-model")
            self.assertIsNotNone(checkpoint.covered_until_message_id)
            self.assertEqual([message.content for message in snapshot], [
                "system",
                "initial",
                "large historical result",
                "latest",
            ])

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

    def test_store_accumulates_model_usage_and_finalizes_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            store = SQLiteSessionStore(db_path)
            session = store.load(session_id="s1", user_id="u1")
            store.start_run(session, "run-1", SessionMetadata())

            store.record_model_response(
                session,
                "run-1",
                ModelResponse(
                    provider="openai-compatible",
                    model="deepseek-v4-pro",
                    usage=ModelUsage(
                        input_tokens=100,
                        output_tokens=20,
                        cache_read_tokens=30,
                        cache_write_tokens=4,
                        reasoning_tokens=5,
                        cost_usd=0.01,
                    ),
                ),
            )
            store.record_model_response(
                session,
                "run-1",
                ModelResponse(
                    provider="openai-compatible",
                    model="deepseek-v4-pro",
                    usage=ModelUsage(
                        input_tokens=50,
                        output_tokens=10,
                        cost_usd=0.005,
                    ),
                ),
            )
            store.finalize(session, "run-1", status="success")

            with sqlite3.connect(db_path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    "SELECT * FROM sessions WHERE id = 's1'"
                ).fetchone()

            self.assertEqual(row["provider"], "openai-compatible")
            self.assertEqual(row["model"], "deepseek-v4-pro")
            self.assertEqual(row["input_tokens"], 150)
            self.assertEqual(row["output_tokens"], 30)
            self.assertEqual(row["cache_read_tokens"], 30)
            self.assertEqual(row["cache_write_tokens"], 4)
            self.assertEqual(row["reasoning_tokens"], 5)
            self.assertAlmostEqual(row["estimated_cost_usd"], 0.015)
            self.assertIsNotNone(row["ended_at"])
            self.assertEqual(row["end_reason"], "success")

            run = store.get_run("run-1")
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.session_id, "s1")
            self.assertEqual(run.input_tokens, 150)
            self.assertEqual(run.output_tokens, 30)
            self.assertAlmostEqual(run.estimated_cost_usd or 0, 0.015)
            self.assertIsNotNone(run.completed_at)
            self.assertEqual(run.completion_reason, "success")

    def test_store_marks_previous_session_run_interrupted_when_next_run_starts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            store = SQLiteSessionStore(db_path)
            session = store.load(session_id="s1", user_id="u1")
            store.start_run(session, "run-1", SessionMetadata())

            restarted_store = SQLiteSessionStore(db_path)
            restarted_store.start_run(session, "run-2", SessionMetadata())

            run = restarted_store.get_run("run-1")
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "interrupted")
            self.assertEqual(run.completion_reason, "superseded_by_new_run")
            self.assertIsNotNone(run.completed_at)

    def test_run_message_boundary_uses_global_message_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            first = store.load(session_id="s1", user_id="u1")
            second = store.load(session_id="s2", user_id="u1")
            store.append(first, Message(role="user", content="first"))
            store.append(second, Message(role="user", content="other session"))

            store.start_run(first, "run-1", SessionMetadata())
            store.append(first, Message(role="user", content="next"))
            store.finalize(first, "run-1", status="success")

            run = store.get_run("run-1")
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.start_message_id, 3)
            self.assertEqual(run.end_message_id, 3)

    def test_append_round_trips_message_execution_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            session = store.load(session_id="s1", user_id="u1")
            store.append(
                session,
                Message(
                    role="assistant",
                    content="done",
                    provider="openai-compatible",
                    model="test-model",
                    token_count=12,
                    finish_reason="stop",
                ),
            )
            store.append(
                session,
                Message(
                    role="tool",
                    content="result",
                    tool_call_id="tc1",
                    tool_name="read_file",
                ),
            )

            restored = store.snapshot(session)

            self.assertEqual(restored[0].provider, "openai-compatible")
            self.assertEqual(restored[0].model, "test-model")
            self.assertEqual(restored[0].token_count, 12)
            self.assertEqual(restored[0].finish_reason, "stop")
            self.assertEqual(restored[1].tool_name, "read_file")

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

            english_hits = store.discover_sessions(query="sqlite lock", user_id="u1")
            chinese_hits = store.discover_sessions(query="简洁直接", user_id="u1")

            self.assertEqual([hit.session_id for hit in english_hits], ["s1"])
            self.assertEqual([hit.session_id for hit in chinese_hits], ["s2"])
            view = store.recall_around(
                session_id="s1",
                message_id=english_hits[0].matched_message.id,
                user_id="u1",
                window=1,
            )
            self.assertIsNotNone(view)
            self.assertEqual([item.content for item in view.messages], [
                "debug sqlite lock contention",
                "use bounded retry",
            ])
            self.assertTrue(view.messages[0].anchor)


if __name__ == "__main__":
    unittest.main()
