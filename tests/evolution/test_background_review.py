from navi_agent.evolution import BackgroundSkillReviewWorker
from navi_agent.telemetry import RuntimeTrace


def test_background_skill_review_worker_runs_submitted_trace() -> None:
    reviewed = []
    worker = BackgroundSkillReviewWorker(review_trace=reviewed.append)
    trace = RuntimeTrace(
        session_id="s1",
        user_id="u1",
        user_message="hello",
        final_response="ok",
        status="success",
    )

    worker.submit(trace, review_memory=True, review_skill=True)
    submitted = worker.status()
    assert submitted.submitted_count == 1
    assert submitted.pending_count >= 0
    assert submitted.running
    worker.drain()

    assert len(reviewed) == 1
    assert reviewed[0].trace == trace
    assert reviewed[0].review_memory
    assert reviewed[0].review_skill
    drained = worker.status()
    assert drained.completed_count == 1
    assert drained.failed_count == 0
    assert drained.pending_count == 0


def test_background_skill_review_worker_survives_review_error() -> None:
    reviewed = []

    def review(task):
        reviewed.append(task.trace.trace_id)
        if len(reviewed) == 1:
            raise RuntimeError("boom")

    worker = BackgroundSkillReviewWorker(review_trace=review)
    first = RuntimeTrace(
        session_id="s1",
        user_id="u1",
        user_message="first",
        final_response="ok",
        status="success",
        trace_id="trace-1",
    )
    second = RuntimeTrace(
        session_id="s2",
        user_id="u1",
        user_message="second",
        final_response="ok",
        status="success",
        trace_id="trace-2",
    )

    worker.submit(first, review_skill=True)
    worker.submit(second, review_skill=True)
    worker.drain()

    assert reviewed == ["trace-1", "trace-2"]
    status = worker.status()
    assert status.submitted_count == 2
    assert status.completed_count == 1
    assert status.failed_count == 1
    assert status.pending_count == 0
