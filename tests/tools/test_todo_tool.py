import unittest

from navi_agent.runtime import ToolContext
from navi_agent.tools import TodoStore, TodoTool


class TodoStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = TodoStore()

    def test_add_and_list(self) -> None:
        self.store.add("u1", "A")
        self.store.add("u1", "B")
        self.assertEqual(len(self.store.list("u1")), 2)

    def test_user_isolation(self) -> None:
        self.store.add("u1", "A")
        self.store.add("u2", "B")
        self.assertEqual(len(self.store.list("u1")), 1)
        self.assertEqual(len(self.store.list("u2")), 1)

    def test_update_and_remove(self) -> None:
        item = self.store.add("u1", "Old")
        updated = self.store.update("u1", item.id, content="New", status="completed")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.content, "New")
        self.store.remove("u1", item.id)
        self.assertIsNone(self.store.get("u1", item.id))

    def test_reorder(self) -> None:
        a = self.store.add("u1", "A")
        b = self.store.add("u1", "B")
        self.store.reorder("u1", [b.id, a.id])
        self.assertEqual([i.id for i in self.store.list("u1")], [b.id, a.id])


class TodoToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = TodoStore()
        self.tool = TodoTool(store=self.store)
        self.ctx = ToolContext(session_id="s1", user_id="u_test", iteration=1)

    def test_add_list_update_remove(self) -> None:
        r = self.tool.invoke(self.ctx, action="add", content="Task")
        iid = r.structured_content["id"]
        self.assertEqual(r.status, "success")

        r = self.tool.invoke(self.ctx, action="list")
        self.assertEqual(len(r.structured_content["items"]), 1)

        r = self.tool.invoke(self.ctx, action="update", id=iid, status="completed")
        self.assertEqual(r.structured_content["status"], "completed")

        r = self.tool.invoke(self.ctx, action="remove", id=iid)
        self.assertEqual(r.status, "success")
        self.assertEqual(len(self.tool.invoke(self.ctx, action="list").structured_content["items"]), 0)

    def test_reorder(self) -> None:
        ids = []
        for label in ("A", "B", "C"):
            r = self.tool.invoke(self.ctx, action="add", content=label)
            ids.append(r.structured_content["id"])
        self.tool.invoke(self.ctx, action="reorder", ids=list(reversed(ids)))
        ordered = self.tool.invoke(self.ctx, action="list").structured_content["items"]
        self.assertEqual([i["id"] for i in ordered], list(reversed(ids)))

    def test_errors(self) -> None:
        self.assertEqual(self.tool.invoke(self.ctx, action="add").status, "error")
        self.assertEqual(self.tool.invoke(self.ctx, action="update", id="bad", status="done").status, "error")
        self.assertEqual(self.tool.invoke(self.ctx, action="remove", id="bad").status, "error")
        self.assertEqual(self.tool.invoke(self.ctx, action="fly").status, "error")

    def test_registered_in_core_toolset(self) -> None:
        from navi_agent.tools.defaults import build_default_tool_registry
        schemas = build_default_tool_registry().schemas(enabled_toolsets=["core"])
        self.assertIn("todo", {s["name"] for s in schemas})
