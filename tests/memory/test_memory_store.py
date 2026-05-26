import unittest

from navi_agent.memory import InMemoryMemoryStore, MemoryRecord


class InMemoryMemoryStoreTests(unittest.TestCase):
    def test_list_for_user_filters_records(self) -> None:
        store = InMemoryMemoryStore(
            records=[
                MemoryRecord(user_id="u1", content="Likes Python"),
                MemoryRecord(user_id="u2", content="Likes Go"),
            ]
        )

        records = store.list_for_user("u1")

        self.assertEqual(records, [MemoryRecord(user_id="u1", content="Likes Python")])

    def test_add_for_user_appends_record(self) -> None:
        store = InMemoryMemoryStore()

        store.add_for_user("u1", "Prefers CLI tools")

        self.assertEqual(
            store.list_for_user("u1"),
            [MemoryRecord(user_id="u1", content="Prefers CLI tools")],
        )


if __name__ == "__main__":
    unittest.main()
