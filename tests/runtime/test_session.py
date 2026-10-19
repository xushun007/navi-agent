import unittest

from navi_agent.runtime.models import Message, SessionGoalStatus
from navi_agent.runtime.sessions.memory import InMemorySessionStore


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

    def test_lists_recent_sessions_for_user(self) -> None:
        first = self.store.load("s1", "u1")
        self.store.append(first, Message(role="user", content="hello"))
        self.store.load("s2", "u2")

        sessions = self.store.list_sessions("u1")

        self.assertTrue(self.store.has_session("s1", "u1"))
        self.assertFalse(self.store.has_session("s1", "u2"))
        self.assertEqual([session.session_id for session in sessions], ["s1"])
        self.assertEqual(sessions[0].message_count, 1)

    def test_goal_lifecycle_is_scoped_to_the_session_owner(self) -> None:
        self.store.load("s1", "u1")

        goal = self.store.set_goal("s1", "u1", "Ship the feature")
        paused = self.store.update_goal_status("s1", "u1", SessionGoalStatus.PAUSED)

        self.assertEqual(goal.status, SessionGoalStatus.ACTIVE)
        self.assertEqual(paused.status if paused else None, SessionGoalStatus.PAUSED)
        self.assertIsNone(self.store.get_goal("s1", "u2"))
        self.assertTrue(self.store.clear_goal("s1", "u1"))
        self.assertIsNone(self.store.get_goal("s1", "u1"))
