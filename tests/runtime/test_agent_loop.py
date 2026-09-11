import unittest

from navi_agent.runtime.agent.control import RunCancelledError
from navi_agent.runtime.agent.loop import AgentLoop
from navi_agent.runtime.agent.model_invoker import ModelInvocation
from navi_agent.runtime.models import ModelResponse, ToolCall
from navi_agent.tooling import ToolResult


def invocation(response: ModelResponse) -> ModelInvocation:
    return ModelInvocation(
        response=response,
        started_at="2026-01-01T00:00:00.000+00:00",
        completed_at="2026-01-01T00:00:01.000+00:00",
        duration_ms=1000,
    )


class AgentLoopTest(unittest.TestCase):
    def test_completes_after_tools_and_a_final_response(self) -> None:
        responses = iter(
            [
                invocation(
                    ModelResponse(
                        tool_calls=[ToolCall(id="call-1", name="echo", arguments={})]
                    )
                ),
                invocation(ModelResponse(content="done")),
            ]
        )
        events = []

        outcome = AgentLoop(max_iterations=3).run(
            is_cancelled=lambda: False,
            on_iteration_started=lambda iteration: events.append(("iteration", iteration)),
            invoke_model=lambda iteration: next(responses),
            on_model_response=lambda iteration, _response, discarded: events.append(
                ("model", iteration, discarded)
            ),
            execute_tools=lambda iteration, _response: events.append(("tools", iteration)),
        )

        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.iteration, 2)
        self.assertEqual(outcome.invocation.response.content, "done")
        self.assertEqual(
            events,
            [
                ("iteration", 1),
                ("model", 1, False),
                ("tools", 1),
                ("iteration", 2),
                ("model", 2, False),
            ],
        )

    def test_returns_waiting_for_pending_interaction(self) -> None:
        pending = ToolResult.ok(
            name="ask",
            content="continue?",
            structured_content={"interaction_pending": True},
        ).bind("call-1")

        outcome = AgentLoop(max_iterations=3).run(
            is_cancelled=lambda: False,
            on_iteration_started=lambda _iteration: None,
            invoke_model=lambda _iteration: invocation(
                ModelResponse(tool_calls=[ToolCall(id="call-1", name="ask", arguments={})])
            ),
            on_model_response=lambda _iteration, _response, _discarded: None,
            execute_tools=lambda _iteration, _response: pending,
        )

        self.assertEqual(outcome.status, "waiting")
        self.assertIs(outcome.pending_result, pending)

    def test_reports_model_failure_and_transport_cancellation(self) -> None:
        failure = RuntimeError("offline")

        failed = AgentLoop(max_iterations=1).run(
            is_cancelled=lambda: False,
            on_iteration_started=lambda _iteration: None,
            invoke_model=lambda _iteration: (_ for _ in ()).throw(failure),
            on_model_response=lambda _iteration, _response, _discarded: None,
            execute_tools=lambda _iteration, _response: None,
        )
        cancelled = AgentLoop(max_iterations=1).run(
            is_cancelled=lambda: False,
            on_iteration_started=lambda _iteration: None,
            invoke_model=lambda _iteration: (_ for _ in ()).throw(RunCancelledError()),
            on_model_response=lambda _iteration, _response, _discarded: None,
            execute_tools=lambda _iteration, _response: None,
        )

        self.assertEqual(failed.status, "failed")
        self.assertIs(failed.error, failure)
        self.assertEqual(cancelled.status, "cancelled")

    def test_discards_response_when_cancelled_during_model_call(self) -> None:
        cancelled = False
        observations = []

        def invoke(_iteration):
            nonlocal cancelled
            cancelled = True
            return invocation(ModelResponse(content="stale"))

        outcome = AgentLoop(max_iterations=1).run(
            is_cancelled=lambda: cancelled,
            on_iteration_started=lambda _iteration: None,
            invoke_model=invoke,
            on_model_response=lambda _iteration, response, discarded: observations.append(
                (response.response.content, discarded)
            ),
            execute_tools=lambda _iteration, _response: None,
        )

        self.assertEqual(outcome.status, "cancelled")
        self.assertEqual(observations, [("stale", True)])

    def test_stops_at_iteration_limit(self) -> None:
        outcome = AgentLoop(max_iterations=2).run(
            is_cancelled=lambda: False,
            on_iteration_started=lambda _iteration: None,
            invoke_model=lambda iteration: invocation(
                ModelResponse(
                    tool_calls=[ToolCall(id=f"call-{iteration}", name="echo", arguments={})]
                )
            ),
            on_model_response=lambda _iteration, _response, _discarded: None,
            execute_tools=lambda _iteration, _response: None,
        )

        self.assertEqual(outcome.status, "iteration_limit")
        self.assertEqual(outcome.iteration, 2)


if __name__ == "__main__":
    unittest.main()
