import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import EvalCase
from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import RuntimeTrace
from navi_agent.healthcheck import (
    compare_healthcheck_workflow_results,
    get_healthcheck_task,
    get_healthcheck_workflow,
    list_healthcheck_tasks,
    list_healthcheck_workflows,
    replay_healthcheck_workflow,
    run_healthcheck_task,
    run_healthcheck_workflow,
    HealthcheckWorkflowService,
)


class FakeApp:
    def __init__(self) -> None:
        self.calls = []
        self.trace_counter = 0
        self.saved_eval_cases = []
        self.saved_candidates = []

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

    def add_eval_case(self, eval_case) -> None:
        self.saved_eval_cases.append(eval_case)

    def add_candidate(self, candidate) -> None:
        self.saved_candidates.append(candidate)

    def list_candidates(self, limit=50, status=None):
        return list(reversed(self.saved_candidates[-limit:]))

    def list_eval_cases(self, limit=50):
        return list(reversed(self.saved_eval_cases[-limit:]))


class HealthcheckTests(unittest.TestCase):
    def test_list_healthcheck_tasks_returns_sorted_tasks(self) -> None:
        tasks = list_healthcheck_tasks()

        self.assertGreaterEqual(len(tasks), 4)
        self.assertEqual([task.name for task in tasks], sorted(task.name for task in tasks))

    def test_get_healthcheck_task_returns_task(self) -> None:
        task = get_healthcheck_task("config-check")

        self.assertEqual(task.name, "config-check")
        self.assertIn("config.example.yaml", task.prompt)

    def test_get_healthcheck_task_raises_for_unknown_task(self) -> None:
        with self.assertRaises(ValueError):
            get_healthcheck_task("missing")

    def test_list_healthcheck_workflows_returns_sorted_workflows(self) -> None:
        workflows = list_healthcheck_workflows()

        self.assertGreaterEqual(len(workflows), 2)
        self.assertEqual([workflow.name for workflow in workflows], sorted(workflow.name for workflow in workflows))

    def test_get_healthcheck_workflow_returns_workflow(self) -> None:
        workflow = get_healthcheck_workflow("agent-healthcheck")

        self.assertEqual(workflow.name, "agent-healthcheck")
        self.assertEqual(workflow.steps[0], "config-check")

    def test_get_healthcheck_workflow_raises_for_unknown_workflow(self) -> None:
        with self.assertRaises(ValueError):
            get_healthcheck_workflow("missing")

    def test_run_healthcheck_task_uses_preset_prompt(self) -> None:
        app = FakeApp()

        result = run_healthcheck_task(
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

    def test_run_healthcheck_workflow_reuses_single_session_across_steps(self) -> None:
        app = FakeApp()

        workflow_result = run_healthcheck_workflow(
            app=app,
            workflow_name="product-orientation",
            user_id="u1",
            session_id="wf-1",
            system_prompt="system",
        )

        self.assertEqual(workflow_result.workflow.name, "product-orientation")
        self.assertEqual(workflow_result.session_id, "wf-1")
        self.assertEqual(workflow_result.user_id, "u1")
        self.assertEqual(workflow_result.system_prompt, "system")
        self.assertEqual(len(workflow_result.steps), 2)
        self.assertEqual([request.session_id for request in app.calls], ["wf-1", "wf-1"])
        self.assertEqual([step.trace_id for step in workflow_result.steps], ["trace-1", "trace-2"])
        self.assertEqual([step.trace_status for step in workflow_result.steps], ["success", "success"])

    def test_replay_healthcheck_workflow_uses_new_session_id(self) -> None:
        app = FakeApp()
        source = run_healthcheck_workflow(
            app=app,
            workflow_name="product-orientation",
            user_id="u1",
            session_id="wf-1",
            system_prompt="system",
        )

        replay = replay_healthcheck_workflow(
            app=app,
            workflow_result=source,
        )

        self.assertNotEqual(replay.session_id, "wf-1")
        self.assertTrue(replay.session_id.startswith("wf-1:replay:"))
        self.assertEqual(replay.workflow.name, source.workflow.name)
        self.assertEqual(replay.user_id, "u1")

    def test_compare_healthcheck_workflow_results_computes_score_delta(self) -> None:
        source = run_healthcheck_workflow(
            app=FakeApp(),
            workflow_name="product-orientation",
            user_id="u1",
            session_id="wf-1",
            system_prompt="system",
        )
        replay = run_healthcheck_workflow(
            app=FakeApp(),
            workflow_name="product-orientation",
            user_id="u1",
            session_id="wf-2",
            system_prompt="system",
        )

        comparison = compare_healthcheck_workflow_results(source, replay)

        self.assertEqual(comparison.workflow_name, "product-orientation")
        self.assertEqual(comparison.source_session_id, "wf-1")
        self.assertEqual(comparison.replay_session_id, "wf-2")
        self.assertEqual(len(comparison.step_comparisons), 2)
        self.assertEqual(comparison.score_delta, 0.0)
        self.assertIsInstance(comparison.eval_case, EvalCase)
        self.assertEqual(comparison.eval_case.status, "unchanged")
        self.assertIsNone(comparison.candidate)

    def test_compare_healthcheck_workflow_results_builds_candidate_for_regression(self) -> None:
        source = run_healthcheck_workflow(
            app=FakeApp(),
            workflow_name="product-orientation",
            user_id="u1",
            session_id="wf-1",
            system_prompt="system",
        )
        replay = run_healthcheck_workflow(
            app=FakeApp(),
            workflow_name="product-orientation",
            user_id="u1",
            session_id="wf-2",
            system_prompt="system",
        )
        replay.steps[0].trace.final_response = ""

        comparison = compare_healthcheck_workflow_results(source, replay)

        self.assertEqual(comparison.eval_case.status, "regressed")
        self.assertIsNotNone(comparison.candidate)
        self.assertEqual(comparison.candidate.target, "prompt")
        self.assertEqual(comparison.candidate.metadata["workflow_name"], "product-orientation")

    def test_healthcheck_workflow_service_finalizes_comparison_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = FakeApp()
            source = run_healthcheck_workflow(
                app=app,
                workflow_name="product-orientation",
                user_id="u1",
                session_id="wf-1",
                system_prompt="system",
            )
            replay = run_healthcheck_workflow(
                app=app,
                workflow_name="product-orientation",
                user_id="u1",
                session_id="wf-2",
                system_prompt="system",
            )
            service = HealthcheckWorkflowService(
                app=app,
                report_root=Path(tmpdir) / "reports",
            )

            result = service.finalize_comparison(source=source, replay=replay)
            report_exists = result.report_dir.exists()

        self.assertTrue(result.eval_case_saved)
        self.assertTrue(report_exists)
        self.assertEqual(len(app.saved_eval_cases), 1)
        self.assertEqual(result.comparison.workflow_name, "product-orientation")


if __name__ == "__main__":
    unittest.main()
