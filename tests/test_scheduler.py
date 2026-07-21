from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from navi_agent.runtime import RuntimeResult
from navi_agent.scheduler import CronJobStore, CronSchedulerService, next_cron_run


class FakeApp:
    def __init__(self) -> None:
        self.requests = []

    def handle(self, request):
        self.requests.append(request)
        return RuntimeResult(
            session_id=request.session_id or "s1",
            status="success",
            final_response="done",
        )


class SchedulerTests(unittest.TestCase):
    def test_next_cron_run_supports_standard_five_field_expression(self) -> None:
        result = next_cron_run(
            "0 9 * * *",
            after=datetime(2026, 7, 21, 8, 58, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    def test_next_cron_run_uses_standard_sunday_weekday(self) -> None:
        result = next_cron_run(
            "0 9 * * 0",
            after=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 26, 9, 0, tzinfo=UTC))

    def test_run_due_uses_tick_lock(self) -> None:
        with TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / ".tick.lock"
            store = CronJobStore(Path(tmpdir) / "jobs.json")
            scheduler = CronSchedulerService(store, lock_path=lock_path)
            scheduler.create_once(
                prompt="check status",
                user_id="u1",
                session_id="s1",
                run_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
            )
            app = FakeApp()

            records = scheduler.run_due(
                app=app,
                now=datetime(2026, 7, 21, 9, 1, tzinfo=UTC),
            )
            lock_exists = lock_path.exists()

        self.assertEqual(len(records), 1)
        self.assertTrue(lock_exists)

    def test_run_due_executes_once_job_and_disables_it(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = CronJobStore(Path(tmpdir) / "jobs.json")
            scheduler = CronSchedulerService(store)
            scheduler.create_once(
                prompt="check status",
                user_id="u1",
                session_id="s1",
                run_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
            )
            app = FakeApp()

            records = scheduler.run_due(
                app=app,
                now=datetime(2026, 7, 21, 9, 1, tzinfo=UTC),
            )
            jobs = store.list_jobs()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "success")
        self.assertEqual(app.requests[0].message, "check status")
        self.assertFalse(jobs[0].enabled)
        self.assertIsNone(jobs[0].next_run_at)

    def test_run_due_reschedules_cron_job(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = CronJobStore(Path(tmpdir) / "jobs.json")
            scheduler = CronSchedulerService(store)
            scheduler.create_cron(
                prompt="poll ci",
                user_id="u1",
                session_id="s1",
                cron="*/5 * * * *",
                now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
            )
            app = FakeApp()

            records = scheduler.run_due(
                app=app,
                now=datetime(2026, 7, 21, 9, 5, tzinfo=UTC),
            )
            jobs = store.list_jobs()

        self.assertEqual(len(records), 1)
        self.assertTrue(jobs[0].enabled)
        self.assertEqual(jobs[0].next_run_at, "2026-07-21T09:10:00+00:00")


if __name__ == "__main__":
    unittest.main()
