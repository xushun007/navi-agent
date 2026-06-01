import unittest

from navi_agent.runtime.models import Message
from navi_agent.runtime.session import InMemorySessionStore


class InMemorySessionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemorySessionStore()

    def test_load_creates_and_reuses_session(self) -> None:
        s1 = self.store.load("s1", "u1")
        s2 = self.store.load("s1", "u1")
        self.assertIs(s1, s2)
        self.assertEqual(s1.session_id, "s1")

    def test_append_and_snapshot(self) -> None:
        state = self.store.load("s1", "u1")
        self.store.append(state, Message(role="user", content="q1"))
        self.store.append(state, Message(role="assistant", content="a1"))
        self.assertEqual(len(self.store.snapshot(state)), 2)

    def test_sessions_are_independent(self) -> None:
        s1 = self.store.load("s1", "u1")
        s2 = self.store.load("s2", "u2")
        self.store.append(s1, Message(role="user", content="hello"))
        self.assertEqual(len(self.store.snapshot(s2)), 0)
