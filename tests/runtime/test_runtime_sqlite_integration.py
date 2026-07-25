import tempfile
import unittest
import sqlite3
from pathlib import Path

from navi_agent.runtime import (
    AgentRuntime,
    ModelResponse,
    ModelUsage,
    SQLiteSessionStore,
)


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)

    def generate(self, request):
        return self._responses.pop(0)


class RuntimeSQLiteIntegrationTests(unittest.TestCase):
    def test_runtime_persists_conversation_in_sqlite_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            runtime = AgentRuntime(
                transport=FakeTransport(
                    [
                        ModelResponse(
                            content="done",
                            provider="openai-compatible",
                            model="test-model",
                            finish_reason="stop",
                            usage=ModelUsage(
                                input_tokens=40,
                                output_tokens=8,
                                cost_usd=0.002,
                            ),
                        )
                    ]
                ),
                session_store=store,
            )

            result = runtime.run_conversation(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                system_prompt="system",
            )

            restored = store.load(session_id="s1", user_id="u1")

            self.assertEqual(result.final_response, "done")
            self.assertEqual(
                [message.role for message in restored.messages],
                ["user", "assistant"],
            )
            self.assertEqual(restored.messages[-1].content, "done")
            self.assertEqual(restored.messages[-1].provider, "openai-compatible")
            self.assertEqual(restored.messages[-1].model, "test-model")
            self.assertEqual(restored.messages[-1].token_count, 8)
            self.assertEqual(restored.messages[-1].finish_reason, "stop")

            with sqlite3.connect(Path(tmpdir) / "state.db") as connection:
                connection.row_factory = sqlite3.Row
                session_row = connection.execute(
                    "SELECT * FROM sessions WHERE id = 's1'"
                ).fetchone()

            self.assertEqual(session_row["provider"], "openai-compatible")
            self.assertEqual(session_row["model"], "test-model")
            self.assertEqual(session_row["input_tokens"], 40)
            self.assertEqual(session_row["output_tokens"], 8)
            self.assertAlmostEqual(session_row["estimated_cost_usd"], 0.002)
            self.assertEqual(session_row["end_reason"], "success")
            self.assertIsNotNone(session_row["ended_at"])

            run = store.get_run(result.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.start_message_id, 1)
            self.assertEqual(run.end_message_id, 2)
            self.assertEqual(run.input_tokens, 40)
            self.assertEqual(run.output_tokens, 8)
            self.assertAlmostEqual(run.estimated_cost_usd or 0, 0.002)


if __name__ == "__main__":
    unittest.main()
