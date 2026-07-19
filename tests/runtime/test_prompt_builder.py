import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from navi_agent.evolution import FileSkillStore
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.runtime.models import ConversationState, Message
from navi_agent.runtime.prompt_builder import (
    BASE_SYSTEM_PROMPT,
    MEMORY_GUIDANCE,
    SKILL_GUIDANCE,
    PromptBuilder,
)


class PromptBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = InMemoryMemoryStore()
        self.builder = PromptBuilder(memory_store=self.memory)

    def test_new_session_with_system_prompt(self) -> None:
        session = ConversationState(session_id="s1", user_id="u1")
        msgs = self.builder.build_initial_messages(session, "hello", system_prompt="Be nice")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "system")
        self.assertIn(BASE_SYSTEM_PROMPT, msgs[0].content)
        self.assertIn("Be nice", msgs[0].content)
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

    def test_new_session_without_extra_context_uses_base_system_prompt(self) -> None:
        session = ConversationState(session_id="s1", user_id="u1")
        msgs = self.builder.build_initial_messages(session, "hello")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "system")
        self.assertIn(BASE_SYSTEM_PROMPT, msgs[0].content)
        self.assertIn(MEMORY_GUIDANCE, msgs[0].content)
        self.assertIn(SKILL_GUIDANCE, msgs[0].content)
        self.assertEqual(msgs[1].role, "user")

    def test_system_prompt_parts_are_ordered(self) -> None:
        self.memory.add_for_user("u1", "Likes Python")
        prompt = self.builder.build_system_prompt(
            user_id="u1",
            user_message="hello",
            system_prompt="Context prompt",
        ).render()

        self.assertLess(prompt.index(BASE_SYSTEM_PROMPT), prompt.index(MEMORY_GUIDANCE))
        self.assertLess(prompt.index(MEMORY_GUIDANCE), prompt.index(SKILL_GUIDANCE))
        self.assertLess(prompt.index(SKILL_GUIDANCE), prompt.index("Context prompt"))
        self.assertLess(prompt.index("Context prompt"), prompt.index("[Memory]"))

    def test_new_session_injects_project_context(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "AGENTS.md").write_text("Use uv for commands.", encoding="utf-8")
            builder = PromptBuilder(project_context_root=root)
            session = ConversationState(session_id="s1", user_id="u1")

            msgs = builder.build_initial_messages(session, "hello")

        self.assertIn("[Project Context]", msgs[0].content)
        self.assertIn("## AGENTS.md", msgs[0].content)
        self.assertIn("Use uv for commands.", msgs[0].content)
        self.assertEqual(builder.last_injected_context_files, ["AGENTS.md"])

    def test_project_context_prefers_navi_md(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".navi.md").write_text("Prefer Navi instructions.", encoding="utf-8")
            (root / "AGENTS.md").write_text("Prefer repo instructions.", encoding="utf-8")
            builder = PromptBuilder(project_context_root=root)

            prompt = builder.build_system_prompt(user_id="u1", user_message="hello").render()

        self.assertIn("## .navi.md", prompt)
        self.assertIn("Prefer Navi instructions.", prompt)
        self.assertNotIn("Prefer repo instructions.", prompt)
        self.assertEqual(builder.last_injected_context_files, [".navi.md"])

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
        self.assertEqual(builder.last_injected_skill_names, ["readme-summary"])

    def test_new_session_with_skill_reference(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_store = FileSkillStore(root)
            skill_store.create(
                name="readme-summary",
                content="\n".join(
                    [
                        "---",
                        "description: Summarize README files",
                        "---",
                        "Use read_file before bash.",
                    ]
                ),
            )
            references_dir = root / "readme-summary" / "references"
            references_dir.mkdir()
            (references_dir / "checks.md").write_text(
                "Run README checks after editing and cite the verified result.",
                encoding="utf-8",
            )
            builder = PromptBuilder(skill_store=skill_store)
            session = ConversationState(session_id="s1", user_id="u1")

            msgs = builder.build_initial_messages(session, "summarize README")

        self.assertIn("reference references/checks.md", msgs[0].content)
        self.assertIn("Run README checks after editing", msgs[0].content)

    def test_injected_skill_names_reset_between_builds(self) -> None:
        with TemporaryDirectory() as tmpdir:
            skill_store = FileSkillStore(Path(tmpdir))
            skill_store.create(
                name="readme-summary",
                content="\n".join(
                    [
                        "---",
                        "description: Summarize README files",
                        "---",
                    ]
                ),
            )
            builder = PromptBuilder(skill_store=skill_store)
            session = ConversationState(session_id="s1", user_id="u1")

            builder.build_initial_messages(session, "summarize README")
            builder.build_initial_messages(session, "unrelated")

        self.assertEqual(builder.last_injected_skill_names, [])

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
