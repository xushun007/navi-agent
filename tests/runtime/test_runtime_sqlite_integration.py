import tempfile
import unittest
from pathlib import Path

from navi_agent.runtime import AgentRuntime, ModelResponse, SQLiteSessionStore


class FakeModelClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def generate(self, messages, tools):
        return self._responses.pop(0)


class RuntimeSQLiteIntegrationTests(unittest.TestCase):
    def test_runtime_persists_conversation_in_sqlite_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "state.db")
            runtime = AgentRuntime(
                model_client=FakeModelClient([ModelResponse(content="done")]),
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
                ["system", "user", "assistant"],
            )
            self.assertEqual(restored.messages[-1].content, "done")


if __name__ == "__main__":
    unittest.main()
