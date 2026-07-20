from __future__ import annotations

import unittest

from navi_agent.telemetry import (
    InMemoryRuntimeEventStore,
    RuntimeStreamEvent,
    RuntimeTrajectoryService,
)


class RuntimeTrajectoryServiceTests(unittest.TestCase):
    def test_render_formats_action_observation_sequence(self) -> None:
        store = InMemoryRuntimeEventStore()
        store.record(
            RuntimeStreamEvent(
                session_id="s1",
                user_id="u1",
                run_id="r1",
                sequence=1,
                kind="action",
                source="user",
                name="user.message",
                payload={"content": "read README"},
            )
        )
        store.record(
            RuntimeStreamEvent(
                session_id="s1",
                user_id="u1",
                run_id="r1",
                sequence=2,
                kind="action",
                source="agent",
                name="model.response",
                iteration=1,
                payload={"tool_calls": [{"name": "read_file"}]},
            )
        )
        store.record(
            RuntimeStreamEvent(
                session_id="s1",
                user_id="u1",
                run_id="r1",
                sequence=3,
                kind="observation",
                source="tool",
                name="tool.result",
                iteration=1,
                payload={"tool_name": "read_file", "status": "success"},
            )
        )

        text = RuntimeTrajectoryService(store).render(session_id="s1")

        self.assertIn("runtime_trajectory:", text)
        self.assertIn("run_id: r1", text)
        self.assertIn("[1] action/user user.message: read README", text)
        self.assertIn("[2] action/agent model.response iter=1: tool_calls=[read_file]", text)
        self.assertIn("[3] observation/tool tool.result iter=1: read_file success", text)

    def test_render_reports_empty_trajectory(self) -> None:
        text = RuntimeTrajectoryService(InMemoryRuntimeEventStore()).render(session_id="missing")

        self.assertIn("runtime_trajectory: none", text)
        self.assertIn("session_id: missing", text)


if __name__ == "__main__":
    unittest.main()
