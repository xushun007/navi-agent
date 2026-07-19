from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from navi_agent.telemetry import RuntimeTrace

from .skill_review import SkillReviewEvidence

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackgroundSkillReviewStatus:
    submitted_count: int
    completed_count: int
    failed_count: int
    pending_count: int
    running: bool


@dataclass(frozen=True, slots=True)
class BackgroundReviewTask:
    trace: RuntimeTrace
    skill_evidence: SkillReviewEvidence | None = None
    review_memory: bool = False
    review_skill: bool = False


class BackgroundSkillReviewWorker:
    def __init__(
        self,
        *,
        review_trace: Callable[[BackgroundReviewTask], None],
    ) -> None:
        self._review_trace = review_trace
        self._queue: queue.Queue[BackgroundReviewTask] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._submitted_count = 0
        self._completed_count = 0
        self._failed_count = 0

    def submit(
        self,
        trace: RuntimeTrace,
        *,
        skill_evidence: SkillReviewEvidence | None = None,
        review_memory: bool = False,
        review_skill: bool = False,
    ) -> None:
        if not review_memory and not review_skill:
            return
        self._ensure_started()
        task = BackgroundReviewTask(
            trace=trace,
            skill_evidence=skill_evidence,
            review_memory=review_memory,
            review_skill=review_skill,
        )
        with self._lock:
            self._submitted_count += 1
        logger.info(
            "Submitted background review: trace_id=%s session_id=%s memory=%s skill=%s skill_evidence_traces=%s pending=%s",
            trace.trace_id,
            trace.session_id,
            review_memory,
            review_skill,
            len(skill_evidence.traces) if skill_evidence is not None else 0,
            self._queue.qsize() + 1,
        )
        self._queue.put(task)

    def drain(self) -> None:
        self._queue.join()

    def status(self) -> BackgroundSkillReviewStatus:
        with self._lock:
            submitted_count = self._submitted_count
            completed_count = self._completed_count
            failed_count = self._failed_count
            running = self._thread is not None and self._thread.is_alive()
        return BackgroundSkillReviewStatus(
            submitted_count=submitted_count,
            completed_count=completed_count,
            failed_count=failed_count,
            pending_count=self._queue.qsize(),
            running=running,
        )

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
            task = self._queue.get()
            trace = task.trace
            try:
                logger.info(
                    "Starting background review: trace_id=%s session_id=%s memory=%s skill=%s",
                    trace.trace_id,
                    trace.session_id,
                    task.review_memory,
                    task.review_skill,
                )
                self._review_trace(task)
                with self._lock:
                    self._completed_count += 1
                logger.info(
                    "Completed background review: trace_id=%s session_id=%s pending=%s",
                    trace.trace_id,
                    trace.session_id,
                    self._queue.qsize(),
                )
            except Exception:
                with self._lock:
                    self._failed_count += 1
                logger.exception("Background review failed: trace_id=%s", trace.trace_id)
            finally:
                self._queue.task_done()
