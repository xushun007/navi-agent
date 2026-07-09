import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from navi_agent.evolution import FileSkillStore
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.runtime.models import ConversationState, Message
from navi_agent.runtime.prompt_builder import PromptBuilder


class PromptBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = InMemoryMemoryStore()
        self.builder = PromptBuilder(memory_store=self.memory)

    def test_new_session_with_system_prompt(self) -> None:
        session = ConversationState(session_id="s1", user_id="u1")
        msgs = self.builder.build_initial_messages(session, "hello", system_prompt="Be nice")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "system")
        self.assertEqual(msgs[1].role, "user")

    def test_new_session_with_memory(self) -> None:
        self.memory.add_for_user("u1", "Likes Python")
        session = ConversationState(session_id="s1", user_id="u1")
        msgs = self.builder.build_initial_messages(session, "hello")
        self.assertEqual(len(msgs), 2)
        self.assertIn("[fact] Likes Python", msgs[0].content)

    def test_new_session_limits_memory_entries(self) -> None:
        for index in range(7):
            self.memory.add_for_user("u1", f"Memory {index}")
        builder = PromptBuilder(memory_store=self.memory, memory_limit=5)
        session = ConversationState(session_id="s1", user_id="u1")

        msgs = builder.build_initial_messages(session, "hello")

        self.assertIn("[fact] Memory 2", msgs[0].content)
        self.assertIn("[fact] Memory 6", msgs[0].content)
        self.assertNotIn("[fact] Memory 0", msgs[0].content)
        self.assertNotIn("[fact] Memory 1", msgs[0].content)

    def test_new_session_without_system_or_memory(self) -> None:
        session = ConversationState(session_id="s1", user_id="u1")
        msgs = self.builder.build_initial_messages(session, "hello")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "user")

    def test_new_session_with_relevant_skill(self) -> None:
        with TemporaryDirectory() as tmpdir:
            skill_store = FileSkillStore(Path(tmpdir))
            skill_store.create(
                name="readme-summary",
                content="\n".join(
                    [
                        "---",
                        "description: Summarize README files and run tests",
                        "---",
                        "Use read_file before bash.",
                    ]
                ),
            )
            builder = PromptBuilder(skill_store=skill_store)
            session = ConversationState(session_id="s1", user_id="u1")

            msgs = builder.build_initial_messages(session, "summarize README")

        self.assertEqual(len(msgs), 2)
        self.assertIn("[Skills]", msgs[0].content)
        self.assertIn("readme-summary: Summarize README files and run tests", msgs[0].content)

    def test_existing_session_skips_system_and_memory(self) -> None:
        self.memory.add_for_user("u1", "Memory")
        session = ConversationState(session_id="s1", user_id="u1")
        session.messages.append(Message(role="user", content="prev"))
        msgs = self.builder.build_initial_messages(session, "follow-up", system_prompt="System")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "follow-up")

    def test_memory_limit_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            PromptBuilder(memory_store=self.memory, memory_limit=0)

    def test_skill_limit_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            PromptBuilder(skill_limit=0)
