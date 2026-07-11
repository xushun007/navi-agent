import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from navi_agent.memory import FileMemoryStore, InMemoryMemoryStore, MemoryRecord


class InMemoryMemoryStoreTests(unittest.TestCase):
    def test_list_for_user_filters_records(self) -> None:
        store = InMemoryMemoryStore(
            records=[
                MemoryRecord(id="m1", user_id="u1", kind="fact", content="Likes Python"),
                MemoryRecord(id="m2", user_id="u2", kind="fact", content="Likes Go"),
            ]
        )

        records = store.list_for_user("u1")

        self.assertEqual(records, [MemoryRecord(id="m1", user_id="u1", kind="fact", content="Likes Python")])

    def test_add_for_user_appends_record(self) -> None:
        store = InMemoryMemoryStore()

        store.add_for_user("u1", "Prefers CLI tools")

        self.assertEqual(
            store.list_for_user("u1"),
            [
                MemoryRecord(
                    id=store.list_for_user("u1")[0].id,
                    user_id="u1",
                    kind="fact",
                    content="Prefers CLI tools",
                )
            ],
        )

    def test_update_and_remove_record(self) -> None:
        store = InMemoryMemoryStore()
        record = store.add_for_user("u1", "Old note")

        updated = store.update_for_user("u1", record.id, "New note")
        removed = store.remove_for_user("u1", record.id)

        self.assertIsNotNone(updated)
        self.assertEqual(updated.content, "New note")
        self.assertTrue(removed)
        self.assertEqual(store.list_for_user("u1"), [])


class FileMemoryStoreTests(unittest.TestCase):
    def test_persists_records_to_memory_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = FileMemoryStore(root)
            fact = store.add_for_user("u1", "Uses Python", kind="fact")
            preference = store.add_for_user("u1", "Prefers concise replies", kind="preference")

            reloaded = FileMemoryStore(root)
            records = reloaded.list_for_user("u1")

        self.assertEqual([record.id for record in records], [fact.id, preference.id])
        self.assertEqual(records[0].content, "Uses Python")
        self.assertEqual(records[1].content, "Prefers concise replies")

    def test_update_and_remove_persist(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = FileMemoryStore(root)
            record = store.add_for_user("u1", "Old note", kind="task")

            updated = store.update_for_user("u1", record.id, "New note")
            removed = FileMemoryStore(root).remove_for_user("u1", record.id)
            records = FileMemoryStore(root).list_for_user("u1")

        self.assertIsNotNone(updated)
        self.assertEqual(updated.content, "New note")
        self.assertTrue(removed)
        self.assertEqual(records, [])

    def test_routes_preferences_to_user_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = FileMemoryStore(root)

            store.add_for_user("u1", "Likes short answers", kind="preference")
            store.add_for_user("u1", "Project uses uv", kind="fact")

            memory_text = (root / "MEMORY.md").read_text(encoding="utf-8")
            user_text = (root / "USER.md").read_text(encoding="utf-8")

        self.assertIn("Project uses uv", memory_text)
        self.assertIn("Likes short answers", user_text)
        self.assertNotIn("Likes short answers", memory_text)


if __name__ == "__main__":
    unittest.main()
