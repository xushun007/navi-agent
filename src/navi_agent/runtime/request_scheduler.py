from __future__ import annotations

from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Condition
from time import monotonic
from typing import Generic, TypeVar, cast


T = TypeVar("T")


@dataclass(slots=True)
class _PendingTask(Generic[T]):
    callback: Callable[[], T]
    future: Future[T]


class SessionTaskScheduler:
    """Run one task per session at a time across a bounded worker pool."""

    def __init__(self, *, max_workers: int = 4) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="navi-session",
        )
        self._condition = Condition()
        self._queues: dict[str, deque[_PendingTask[object]]] = {}
        self._active_sessions: set[str] = set()
        self._accepting = True

    def submit(self, session_id: str, callback: Callable[[], T]) -> Future[T]:
        if not session_id:
            raise ValueError("session_id must not be empty")
        future: Future[T] = Future()
        task = _PendingTask(callback=callback, future=future)
        should_dispatch = False
        with self._condition:
            if not self._accepting:
                raise RuntimeError("scheduler is closed")
            queue = self._queues.setdefault(session_id, deque())
            queue.append(cast(_PendingTask[object], task))
            if session_id not in self._active_sessions:
                self._active_sessions.add(session_id)
                should_dispatch = True
        if should_dispatch:
            self._dispatch_next(session_id)
        return future

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while self._active_sessions:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, *, wait: bool = True) -> None:
        with self._condition:
            if not self._accepting:
                return
            self._accepting = False
        if wait:
            self.wait_for_idle()
        else:
            self._cancel_pending()
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def _dispatch_next(self, session_id: str) -> None:
        with self._condition:
            queue = self._queues.get(session_id)
            if not queue:
                self._active_sessions.discard(session_id)
                self._condition.notify_all()
                return
            task = queue.popleft()
            self._executor.submit(self._execute, session_id, task)

    def _execute(self, session_id: str, task: _PendingTask[object]) -> None:
        if task.future.set_running_or_notify_cancel():
            try:
                task.future.set_result(task.callback())
            except BaseException as exc:
                task.future.set_exception(exc)
        with self._condition:
            queue = self._queues[session_id]
            has_next = bool(queue)
            if not has_next:
                del self._queues[session_id]
                self._active_sessions.remove(session_id)
                self._condition.notify_all()
            if has_next:
                self._dispatch_next(session_id)

    def _cancel_pending(self) -> None:
        with self._condition:
            for session_id, queue in list(self._queues.items()):
                while len(queue) > 0:
                    queue.pop().future.cancel()
                if session_id not in self._active_sessions:
                    del self._queues[session_id]
