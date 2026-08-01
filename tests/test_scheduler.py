from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from navi_agent.runtime import RuntimeResult
from navi_agent.runtime.tasks.cron import (
    CronJobStore,
    CronRunStore,
    CronSchedulerService,
    next_cron_run,
)


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

    def test_run_due_persists_result_for_delivery(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = CronJobStore(Path(tmpdir) / "jobs.json")
            run_store = CronRunStore(Path(tmpdir) / "state.db")
            scheduler = CronSchedulerService(store, run_store=run_store)
            scheduler.create_once(
                prompt="check status",
                user_id="u1",
                session_id="s1",
                run_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
            )

            records = scheduler.run_due(
                app=FakeApp(),
                now=datetime(2026, 7, 21, 9, 1, tzinfo=UTC),
            )
            pending = run_store.list_pending_delivery()

        self.assertEqual(len(records), 1)
        self.assertEqual(pending[0].run_id, records[0].run_id)
        self.assertEqual(pending[0].status, "success")
        self.assertEqual(pending[0].final_response, "done")

    def test_run_due_persists_failure_and_advances_once_job(self) -> None:
        class FailingApp:
            def handle(self, request):
                raise RuntimeError("model unavailable")

        with TemporaryDirectory() as tmpdir:
            store = CronJobStore(Path(tmpdir) / "jobs.json")
            run_store = CronRunStore(Path(tmpdir) / "state.db")
            scheduler = CronSchedulerService(store, run_store=run_store)
            scheduler.create_once(
                prompt="check status",
                user_id="u1",
                session_id="s1",
                run_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
            )

            records = scheduler.run_due(
                app=FailingApp(),
                now=datetime(2026, 7, 21, 9, 1, tzinfo=UTC),
            )
            jobs = store.list_jobs()

        self.assertEqual(records[0].status, "failed")
        self.assertIn("model unavailable", records[0].error)
        self.assertFalse(jobs[0].enabled)

    def test_run_store_marks_abandoned_run_interrupted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = CronJobStore(Path(tmpdir) / "jobs.json")
            scheduler = CronSchedulerService(store)
            job = scheduler.create_once(
                prompt="check status",
                user_id="u1",
                session_id="s1",
                run_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
            )
            run_store = CronRunStore(Path(tmpdir) / "state.db")
            run = run_store.start(
                job,
                scheduled_for=job.next_run_at or "",
                now=datetime(2026, 7, 21, 9, 1, tzinfo=UTC),
            )

            recovered = run_store.recover_interrupted(
                now=datetime(2026, 7, 21, 9, 2, tzinfo=UTC)
            )
            record = run_store.get(run.run_id)

        self.assertEqual(recovered, 1)
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "interrupted")


if __name__ == "__main__":
    unittest.main()
