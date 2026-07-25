import tempfile
import unittest
from pathlib import Path

from navi_agent.events import RuntimeEvent
from navi_agent.runtime import OfflineRuntimeReplay
from navi_agent.telemetry import RuntimeReplayPlanner, RuntimeTrajectory


def event(
    sequence: int,
    name: str,
    metadata: dict[str, object] | None = None,
    *,
    iteration: int | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        session_id="s1",
        user_id="u1",
        run_id="r1",
        sequence=sequence,
        kind="observation",
        source="runtime",
        name=name,
        iteration=iteration,
        metadata=metadata or {},
    )


def write_file_trajectory(path: Path) -> RuntimeTrajectory:
    return RuntimeTrajectory(
        session_id="s1",
        run_id="r1",
        events=[
            event(1, "runtime.started"),
            event(2, "user.message", {"content": "write the file"}),
            event(3, "runtime.context_ready", {"system_prompt": "system"}),
            event(
                4,
                "model.response",
                {
                    "purpose": "agent",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "write_file",
                            "arguments": {
                                "path": str(path),
                                "content": "dangerous",
                            },
                        }
                    ],
                },
                iteration=1,
            ),
            event(
                5,
                "tool.result",
                {
                    "tool_call_id": "tc1",
                    "tool_name": "write_file",
                    "arguments": {
                        "path": str(path),
                        "content": "dangerous",
                    },
                    "status": "success",
                    "content": "written",
                    "structured_content": {"path": str(path)},
                },
                iteration=1,
            ),
            event(
                6,
                "model.response",
                {
                    "purpose": "agent",
                    "content": "done",
                    "tool_calls": [],
                },
                iteration=2,
            ),
            event(
                7,
                "runtime.completed",
                {
                    "status": "success",
                    "final_response": "done",
                    "trajectory_complete": True,
                },
                iteration=2,
            ),
        ],
    )


class OfflineRuntimeReplayTests(unittest.TestCase):
    def test_replays_runtime_control_flow_without_tool_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "must-not-exist.txt"
            plan = RuntimeReplayPlanner().build(write_file_trajectory(target))

            replay = OfflineRuntimeReplay().execute(plan)

            self.assertTrue(replay.verified)
            self.assertEqual(replay.runtime_result.status, "success")
            self.assertEqual(replay.runtime_result.final_response, "done")
            self.assertEqual(replay.runtime_result.tool_results[0].content, "written")
            self.assertFalse(target.exists())

    def test_reports_unconsumed_recorded_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory = write_file_trajectory(Path(tmpdir) / "unused.txt")
            events = [
                item
                for item in trajectory.events
                if item.name != "model.response" or item.iteration != 1
            ]
            plan = RuntimeReplayPlanner().build(
                RuntimeTrajectory(session_id="s1", run_id="r1", events=events)
            )

            replay = OfflineRuntimeReplay().execute(plan)

            self.assertFalse(replay.verified)
            self.assertIn("tool_steps", [item.kind for item in replay.divergences])

    def test_replays_recorded_rate_limit_failure(self) -> None:
        final_response = (
            "模型服务暂时不可用（HTTP 429, RateLimitError）。"
            "请稍后重试；如果持续出现，检查模型服务或网络状态。"
        )
        trajectory = RuntimeTrajectory(
            session_id="s1",
            run_id="r1",
            events=[
                event(1, "runtime.started"),
                event(2, "user.message", {"content": "hello"}),
                event(
                    3,
                    "model.failed",
                    {
                        "error_type": "RateLimitError",
                        "error_message": "quota exhausted",
                        "retryable": True,
                        "http_status": 429,
                    },
                    iteration=1,
                ),
                event(
                    4,
                    "runtime.completed",
                    {
                        "status": "failed",
                        "final_response": final_response,
                        "trajectory_complete": True,
                    },
                    iteration=1,
                ),
            ],
        )
        plan = RuntimeReplayPlanner().build(trajectory)

        replay = OfflineRuntimeReplay().execute(plan)

        self.assertTrue(replay.verified)
        self.assertEqual(replay.runtime_result.status, "failed")
        self.assertEqual(replay.runtime_result.final_response, final_response)


if __name__ == "__main__":
    unittest.main()
