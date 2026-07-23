from __future__ import annotations

import unittest

from navi_agent.events import RuntimeEvent
from navi_agent.runtime import RunStateTracker


def _event(name: str, metadata: dict[str, object] | None = None) -> RuntimeEvent:
    return RuntimeEvent(
        session_id="s1",
        user_id="u1",
        run_id="r1",
        sequence=1,
        kind="observation",
        source="runtime",
        name=name,
        metadata=metadata or {},
    )


class RunStateTrackerTests(unittest.TestCase):
    def test_projects_successful_lifecycle(self) -> None:
        tracker = RunStateTracker()

        tracker.handle(_event("runtime.started"))
        self.assertEqual(tracker.get("s1").status, "running")

        tracker.handle(_event("runtime.completed", {"status": "success"}))
        self.assertEqual(tracker.get("s1").status, "completed")

    def test_preserves_waiting_interaction_on_completed_event(self) -> None:
        tracker = RunStateTracker()

        tracker.handle(
            _event(
                "runtime.waiting",
                {"status": "awaiting_input", "interaction_id": "i1"},
            )
        )
        tracker.handle(_event("runtime.completed", {"status": "awaiting_input"}))

        state = tracker.get("s1")
        self.assertEqual(state.status, "awaiting_input")
        self.assertEqual(state.interaction_id, "i1")

    def test_projects_cancelled_failed_resumed_and_expired_states(self) -> None:
        tracker = RunStateTracker()
        cases = [
            ("runtime.resumed", {}, "resumed"),
            ("runtime.cancelled", {"reason": "user_stop"}, "cancelled"),
            ("runtime.completed", {"status": "failed"}, "failed"),
            ("runtime.interaction_expired", {"interaction_id": "i1"}, "expired"),
        ]

        for name, metadata, expected in cases:
            tracker.handle(_event(name, metadata))
            self.assertEqual(tracker.get("s1").status, expected)
