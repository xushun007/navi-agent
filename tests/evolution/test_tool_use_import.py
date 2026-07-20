from __future__ import annotations

import json
import unittest

from navi_agent.evolution import (
    build_tool_use_case_from_trajectory,
    render_tool_use_case_jsonl,
)
from navi_agent.telemetry import RuntimeStreamEvent, RuntimeTrajectory


class ToolUseImportTests(unittest.TestCase):
    def test_builds_case_from_runtime_trajectory(self) -> None:
        trajectory = RuntimeTrajectory(
            session_id="s/1",
            run_id="runabcdef",
            events=[
                RuntimeStreamEvent(
                    session_id="s/1",
                    user_id="u1",
                    run_id="runabcdef",
                    sequence=1,
                    kind="action",
                    source="user",
                    name="user.message",
                    payload={"content": "读取 README.md"},
                ),
                RuntimeStreamEvent(
                    session_id="s/1",
                    user_id="u1",
                    run_id="runabcdef",
                    sequence=2,
                    kind="action",
                    source="agent",
                    name="tool.call",
                    iteration=2,
                    payload={"tool_name": "read_file", "arguments": {"path": "README.md"}},
                ),
            ],
        )

        case = build_tool_use_case_from_trajectory(trajectory)

        assert case is not None
        self.assertEqual(case.id, "tooluse_replay_s_1_runabcde")
        self.assertEqual(case.level, "L1")
        self.assertEqual(case.prompt, "读取 README.md")
        self.assertEqual(case.required_tools, ["read_file"])
        self.assertEqual(case.expected_args, {"read_file": {"path": "README.md"}})
        self.assertEqual(case.max_iterations, 6)

    def test_render_outputs_jsonl_case(self) -> None:
        trajectory = RuntimeTrajectory(
            session_id="s1",
            run_id="r1",
            events=[
                RuntimeStreamEvent(
                    session_id="s1",
                    user_id="u1",
                    run_id="r1",
                    sequence=1,
                    kind="action",
                    source="user",
                    name="user.message",
                    payload={"content": "hello"},
                )
            ],
        )
        case = build_tool_use_case_from_trajectory(trajectory)

        assert case is not None
        payload = json.loads(render_tool_use_case_jsonl(case))

        self.assertEqual(payload["prompt"], "hello")
        self.assertEqual(payload["source_inspiration"], "runtime-events")

    def test_returns_none_without_user_message(self) -> None:
        trajectory = RuntimeTrajectory(session_id="s1", run_id="r1", events=[])

        self.assertIsNone(build_tool_use_case_from_trajectory(trajectory))


if __name__ == "__main__":
    unittest.main()
