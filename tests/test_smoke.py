import unittest

from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import RuntimeTrace
from navi_agent.smoke import (
    get_smoke_task,
    get_smoke_workflow,
    list_smoke_tasks,
    list_smoke_workflows,
    run_smoke_task,
    run_smoke_workflow,
)


class FakeApp:
    def __init__(self) -> None:
        self.calls = []
        self.trace_counter = 0

    def handle(self, request):
        self.calls.append(request)
        self.trace_counter += 1
        return RuntimeResult(
            session_id=request.session_id or "generated",
            status="success",
            final_response="done",
        )

    def get_latest_trace(self, session_id=None, user_id=None):
        return RuntimeTrace(
            session_id=session_id or "generated",
            user_id=user_id or "u1",
            user_message="prompt",
            final_response="done",
            status="success",
            trace_id=f"trace-{self.trace_counter}",
        )


class SmokeTests(unittest.TestCase):
    def test_list_smoke_tasks_returns_sorted_tasks(self) -> None:
        tasks = list_smoke_tasks()

        self.assertGreaterEqual(len(tasks), 4)
        self.assertEqual([task.name for task in tasks], sorted(task.name for task in tasks))

    def test_get_smoke_task_returns_task(self) -> None:
        task = get_smoke_task("config-check")

        self.assertEqual(task.name, "config-check")
        self.assertIn("config.example.yaml", task.prompt)

    def test_get_smoke_task_raises_for_unknown_task(self) -> None:
        with self.assertRaises(ValueError):
            get_smoke_task("missing")

    def test_list_smoke_workflows_returns_sorted_workflows(self) -> None:
        workflows = list_smoke_workflows()

        self.assertGreaterEqual(len(workflows), 2)
        self.assertEqual([workflow.name for workflow in workflows], sorted(workflow.name for workflow in workflows))

    def test_get_smoke_workflow_returns_workflow(self) -> None:
        workflow = get_smoke_workflow("prototype-baseline")

        self.assertEqual(workflow.name, "prototype-baseline")
        self.assertEqual(workflow.steps[0], "config-check")

    def test_get_smoke_workflow_raises_for_unknown_workflow(self) -> None:
        with self.assertRaises(ValueError):
            get_smoke_workflow("missing")

    def test_run_smoke_task_uses_preset_prompt(self) -> None:
        app = FakeApp()

        result = run_smoke_task(
            app=app,
            task_name="readme-summary",
            user_id="u1",
            session_id="s1",
            system_prompt="system",
        )

        self.assertEqual(result.final_response, "done")
        self.assertEqual(app.calls[0].session_id, "s1")
        self.assertEqual(app.calls[0].user_id, "u1")
        self.assertIn("README.md", app.calls[0].message)

    def test_run_smoke_workflow_reuses_single_session_across_steps(self) -> None:
        app = FakeApp()

        workflow_result = run_smoke_workflow(
            app=app,
            workflow_name="product-orientation",
            user_id="u1",
            session_id="wf-1",
            system_prompt="system",
        )

        self.assertEqual(workflow_result.workflow.name, "product-orientation")
        self.assertEqual(workflow_result.session_id, "wf-1")
        self.assertEqual(len(workflow_result.steps), 2)
        self.assertEqual([request.session_id for request in app.calls], ["wf-1", "wf-1"])
        self.assertEqual([step.trace_id for step in workflow_result.steps], ["trace-1", "trace-2"])
        self.assertEqual([step.trace_status for step in workflow_result.steps], ["success", "success"])


if __name__ == "__main__":
    unittest.main()
