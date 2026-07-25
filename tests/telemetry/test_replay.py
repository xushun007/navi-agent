import unittest

from navi_agent.events import RuntimeEvent
from navi_agent.telemetry import (
    ReplayPlanError,
    RuntimeReplayPlanner,
    RuntimeTrajectory,
)


def event(
    sequence: int,
    name: str,
    metadata: dict[str, object] | None = None,
    *,
    session_id: str = "s1",
    run_id: str = "r1",
    iteration: int | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        session_id=session_id,
        user_id="u1",
        run_id=run_id,
        sequence=sequence,
        kind="observation",
        source="runtime",
        name=name,
        iteration=iteration,
        metadata=metadata or {},
    )


class RuntimeReplayPlannerTests(unittest.TestCase):
    def test_builds_deterministic_plan_from_complete_trajectory(self) -> None:
        trajectory = RuntimeTrajectory(
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
                        "provider": "openai-compatible",
                        "model": "model-1",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "cost_usd": 0.01,
                        },
                        "tool_calls": [
                            {
                                "id": "tc1",
                                "name": "write_file",
                                "arguments": {"path": "a.txt", "content": "hello"},
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
                        "arguments": {"path": "a.txt", "content": "hello"},
                        "status": "success",
                        "content": "written",
                        "metadata": {"duration_ms": 3},
                        "structured_content": {"path": "a.txt"},
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
                        "usage": {"input_tokens": 5, "output_tokens": 1},
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

        plan = RuntimeReplayPlanner().build(trajectory)

        self.assertEqual(plan.source_run_id, "r1")
        self.assertEqual(plan.user_message, "write the file")
        self.assertEqual(plan.system_prompt, "system")
        self.assertEqual(plan.expected_status, "success")
        self.assertEqual(plan.expected_final_response, "done")
        self.assertEqual(len(plan.agent_model_steps), 2)
        self.assertEqual(plan.model_steps[0].response.model, "model-1")
        self.assertEqual(plan.model_steps[0].response.usage.input_tokens, 10)
        self.assertEqual(plan.tool_steps[0].call.name, "write_file")
        self.assertEqual(plan.tool_steps[0].result.content, "written")
        self.assertEqual(
            plan.tool_steps[0].result.structured_content,
            {"path": "a.txt"},
        )

    def test_keeps_context_summary_calls_separate_from_agent_steps(self) -> None:
        trajectory = RuntimeTrajectory(
            session_id="s1",
            run_id="r1",
            events=[
                event(1, "runtime.started"),
                event(2, "user.message", {"content": "continue"}),
                event(
                    3,
                    "model.response",
                    {
                        "purpose": "context_summary",
                        "content": "[Context Summary]\nprior work",
                    },
                ),
                event(
                    4,
                    "model.response",
                    {"purpose": "agent", "content": "done"},
                    iteration=1,
                ),
                event(
                    5,
                    "runtime.completed",
                    {"status": "success", "final_response": "done"},
                    iteration=1,
                ),
            ],
        )

        plan = RuntimeReplayPlanner().build(trajectory)

        self.assertEqual([step.purpose for step in plan.model_steps], ["context_summary", "agent"])
        self.assertEqual(len(plan.agent_model_steps), 1)

    def test_rejects_mixed_runs(self) -> None:
        trajectory = RuntimeTrajectory(
            session_id="s1",
            run_id=None,
            events=[
                event(1, "runtime.started"),
                event(2, "user.message", {"content": "hello"}, run_id="r2"),
            ],
        )

        with self.assertRaisesRegex(ReplayPlanError, "exactly one run"):
            RuntimeReplayPlanner().build(trajectory)

    def test_rejects_incomplete_trajectory(self) -> None:
        trajectory = RuntimeTrajectory(
            session_id="s1",
            run_id="r1",
            events=[
                event(1, "runtime.started"),
                event(2, "user.message", {"content": "hello"}),
                event(
                    3,
                    "runtime.completed",
                    {
                        "status": "success",
                        "final_response": "done",
                        "trajectory_complete": False,
                    },
                ),
            ],
        )

        with self.assertRaisesRegex(ReplayPlanError, "marked incomplete"):
            RuntimeReplayPlanner().build(trajectory)

    def test_rejects_duplicate_event_sequences(self) -> None:
        trajectory = RuntimeTrajectory(
            session_id="s1",
            run_id="r1",
            events=[
                event(1, "runtime.started"),
                event(1, "user.message", {"content": "hello"}),
                event(2, "runtime.completed", {"status": "success"}),
            ],
        )

        with self.assertRaisesRegex(ReplayPlanError, "duplicate event sequences"):
            RuntimeReplayPlanner().build(trajectory)


if __name__ == "__main__":
    unittest.main()
