import unittest

from navi_agent.memory import InMemoryMemoryStore
from navi_agent.runtime import ToolContext
from navi_agent.tools import MemoryTool


class MemoryToolTests(unittest.TestCase):
    def test_adds_and_lists_records(self) -> None:
        store = InMemoryMemoryStore()
        tool = MemoryTool(memory_store=store)

        add_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=1),
            action="add",
            kind="preference",
            content="Likes short answers",
        )
        list_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=2),
            action="list",
        )

        self.assertIn("stored", add_result.content)
        self.assertEqual(add_result.structured_content["content"], "Likes short answers")
        self.assertEqual(add_result.structured_content["kind"], "preference")
        self.assertIn("Likes short answers", list_result.content)
        self.assertEqual(list_result.structured_content["records"][0]["content"], "Likes short answers")

    def test_updates_and_removes_records(self) -> None:
        store = InMemoryMemoryStore()
        tool = MemoryTool(memory_store=store)
        add_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=1),
            action="add",
            kind="task",
            content="Old note",
        )
        record_id = add_result.structured_content["content"] and store.list_for_user("u1")[0].id

        update_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=2),
            action="update",
            id=record_id,
            content="New note",
        )
        remove_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=3),
            action="remove",
            id=record_id,
        )

        self.assertEqual(update_result.content, "memory_updated")
        self.assertEqual(update_result.structured_content["content"], "New note")
        self.assertEqual(remove_result.content, "memory_removed")
        self.assertEqual(store.list_for_user("u1"), [])
