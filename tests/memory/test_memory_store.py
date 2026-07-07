import unittest

from navi_agent.memory import InMemoryMemoryStore, MemoryRecord


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


if __name__ == "__main__":
    unittest.main()
