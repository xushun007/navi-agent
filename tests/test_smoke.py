import unittest

from navi_agent.runtime import RuntimeResult
from navi_agent.smoke import get_smoke_task, list_smoke_tasks, run_smoke_task


class FakeApp:
    def __init__(self) -> None:
        self.calls = []

    def handle(self, request):
        self.calls.append(request)
        return RuntimeResult(
            session_id=request.session_id or "generated",
            status="success",
            final_response="done",
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


if __name__ == "__main__":
    unittest.main()
