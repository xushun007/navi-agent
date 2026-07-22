from __future__ import annotations

import unittest

from navi_agent.runtime import ActiveRunRegistry


class ActiveRunRegistryTests(unittest.TestCase):
    def test_cancels_only_matching_active_run(self) -> None:
        registry = ActiveRunRegistry()
        token = registry.start("session-1")

        self.assertTrue(registry.cancel("session-1", "user_stop"))
        self.assertTrue(token.is_cancelled)
        self.assertEqual(token.reason, "user_stop")
        self.assertFalse(registry.cancel("session-2"))

        registry.finish("session-1", token)
        self.assertFalse(registry.is_active("session-1"))

    def test_rejects_overlapping_runs_in_same_session(self) -> None:
        registry = ActiveRunRegistry()
        registry.start("session-1")

        with self.assertRaisesRegex(RuntimeError, "active run"):
            registry.start("session-1")
