from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from navi_agent.telemetry import RuntimeTrace

logger = logging.getLogger(__name__)


class BackgroundSkillReviewWorker:
    def __init__(
        self,
        *,
        review_trace: Callable[[RuntimeTrace], None],
    ) -> None:
        self._review_trace = review_trace
        self._queue: queue.Queue[RuntimeTrace] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def submit(self, trace: RuntimeTrace) -> None:
        self._ensure_started()
        self._queue.put(trace)

    def drain(self) -> None:
        self._queue.join()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name="navi-skill-review",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while True:
            trace = self._queue.get()
            try:
                self._review_trace(trace)
            except Exception:
                logger.exception("Background skill review failed: trace_id=%s", trace.trace_id)
            finally:
                self._queue.task_done()
