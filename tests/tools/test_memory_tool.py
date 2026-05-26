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
            content="Likes short answers",
        )
        list_result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=2),
            action="list",
        )

        self.assertIn("stored", add_result.content)
        self.assertEqual(add_result.structured_content["content"], "Likes short answers")
        self.assertIn("Likes short answers", list_result.content)
        self.assertEqual(list_result.structured_content["records"], ["Likes short answers"])
