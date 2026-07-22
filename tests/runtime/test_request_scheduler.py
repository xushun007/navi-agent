from __future__ import annotations

from threading import Event, Lock
import unittest

from navi_agent.runtime import SessionTaskScheduler


class SessionTaskSchedulerTests(unittest.TestCase):
    def test_serializes_tasks_for_same_session_in_submission_order(self) -> None:
        scheduler = SessionTaskScheduler(max_workers=2)
        first_started = Event()
        release_first = Event()
        second_started = Event()
        order: list[str] = []

        def first() -> None:
            first_started.set()
            release_first.wait(1)
            order.append("first")

        def second() -> None:
            second_started.set()
            order.append("second")

        scheduler.submit("session-1", first)
        scheduler.submit("session-1", second)

        self.assertTrue(first_started.wait(1))
        self.assertFalse(second_started.wait(0.05))
        release_first.set()
        self.assertTrue(scheduler.wait_for_idle(1))
        scheduler.close()

        self.assertEqual(order, ["first", "second"])

    def test_runs_different_sessions_concurrently(self) -> None:
        scheduler = SessionTaskScheduler(max_workers=2)
        both_started = Event()
        release = Event()
        lock = Lock()
        started = 0

        def task() -> None:
            nonlocal started
            with lock:
                started += 1
                if started == 2:
                    both_started.set()
            release.wait(1)

        scheduler.submit("session-1", task)
        scheduler.submit("session-2", task)

        self.assertTrue(both_started.wait(1))
        release.set()
        self.assertTrue(scheduler.wait_for_idle(1))
        scheduler.close()

    def test_failure_does_not_block_next_session_task(self) -> None:
        scheduler = SessionTaskScheduler(max_workers=1)
        completed = Event()

        failed = scheduler.submit("session-1", lambda: 1 / 0)
        scheduler.submit("session-1", completed.set)

        self.assertTrue(completed.wait(1))
        self.assertIsInstance(failed.exception(), ZeroDivisionError)
        scheduler.close()

    def test_rejects_new_tasks_after_close(self) -> None:
        scheduler = SessionTaskScheduler()
        scheduler.close()

        with self.assertRaisesRegex(RuntimeError, "closed"):
            scheduler.submit("session-1", lambda: None)
