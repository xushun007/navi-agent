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

    worker.submit(trace)
    worker.drain()

    assert reviewed == [trace]


def test_background_skill_review_worker_survives_review_error() -> None:
    reviewed = []

    def review(trace):
        reviewed.append(trace.trace_id)
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

    worker.submit(first)
    worker.submit(second)
    worker.drain()

    assert reviewed == ["trace-1", "trace-2"]
