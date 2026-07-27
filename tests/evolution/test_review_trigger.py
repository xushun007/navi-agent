import pytest

from navi_agent.evolution import NudgeReviewTriggerPolicy
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


def test_memory_nudge_is_acknowledged_after_review_enqueue() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=2, skill_tool_interval=0)
    first_trace = _trace(trace_id="trace-1")
    second_trace = _trace(trace_id="trace-2")

    first = policy.decide(first_trace)
    second = policy.decide(second_trace)

    assert not first.should_review
    assert second.review_memory
    assert policy.turns_since_memory == 2

    policy.acknowledge(second_trace, second)

    assert policy.turns_since_memory == 0


def test_skill_nudge_counts_every_tool_execution_until_acknowledged() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=3)
    first_trace = _trace(trace_id="trace-1", tool_count=2)
    second_trace = _trace(trace_id="trace-2", tool_count=2)

    first = policy.decide(first_trace)
    second = policy.decide(second_trace)

    assert not first.should_review
    assert second.review_skill
    assert second.reasons == ["skill_nudge_counter"]
    assert policy.tool_executions_since_skill == 4

    policy.acknowledge(second_trace, second)

    assert policy.tool_executions_since_skill == 1


def test_retrying_same_trace_does_not_double_count_unacknowledged_work() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=2, skill_tool_interval=1)
    trace = _trace(trace_id="trace-1", tool_count=1)

    first = policy.decide(trace)
    retry = policy.decide(trace)

    assert first.review_skill
    assert retry.review_skill
    assert policy.turns_since_memory == 1
    assert policy.tool_executions_since_skill == 1


def test_failed_trace_does_not_increment_nudges() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=1, skill_tool_interval=1)

    decision = policy.decide(
        _trace(trace_id="trace-1", status="failed", final_response="", tool_count=1)
    )

    assert not decision.should_review
    assert policy.turns_since_memory == 0
    assert policy.tool_executions_since_skill == 0


def test_unavailable_capabilities_do_not_increment_nudges() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=1, skill_tool_interval=1)

    decision = policy.decide(
        _trace(trace_id="trace-1", tool_count=1),
        memory_available=False,
        skill_available=False,
    )

    assert not decision.should_review
    assert policy.turns_since_memory == 0
    assert policy.tool_executions_since_skill == 0


def test_successful_memory_write_resets_memory_nudge() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=2, skill_tool_interval=0)
    policy.decide(_trace(trace_id="trace-1", session_id="s1"))

    decision = policy.decide(
        _trace(
            trace_id="trace-2",
            session_id="s2",
            tool_executions=[_execution("memory")],
        )
    )

    assert not decision.should_review
    assert policy.turns_since_memory == 0


def test_skill_view_counts_as_skill_review_evidence() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=3)
    policy.decide(_trace(trace_id="trace-1", tool_count=2))

    decision = policy.decide(
        _trace(trace_id="trace-2", tool_executions=[_execution("skill_view")])
    )

    assert decision.review_skill
    assert policy.tool_executions_since_skill == 3


def test_successful_skill_manage_write_resets_skill_nudge() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=3)
    policy.decide(_trace(trace_id="trace-1", tool_count=2))

    decision = policy.decide(
        _trace(
            trace_id="trace-2",
            tool_executions=[_execution("skill_manage", action="append")],
        )
    )

    assert not decision.review_skill
    assert policy.tool_executions_since_skill == 0


def test_failed_or_read_only_skill_manage_does_not_reset_counter() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=4)
    policy.decide(_trace(trace_id="trace-1", tool_count=2))
    policy.decide(
        _trace(
            trace_id="trace-2",
            tool_executions=[
                _execution("skill_manage", action="list"),
                _execution("skill_manage", action="append", status="error"),
            ],
        )
    )

    assert policy.tool_executions_since_skill == 4


def test_hydrates_counters_from_trace_history() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=3, skill_tool_interval=4)

    policy.hydrate(
        [
            _trace(trace_id="trace-1", tool_count=2),
            _trace(trace_id="trace-2", tool_count=1),
        ]
    )

    assert policy.turns_since_memory == 2
    assert policy.tool_executions_since_skill == 3
    decision = policy.decide(_trace(trace_id="trace-3", tool_count=1))
    assert decision.review_memory
    assert decision.review_skill


def test_counter_state_is_isolated_by_session() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=2)

    first_session = policy.decide(
        _trace(trace_id="trace-1", session_id="s1", tool_count=1)
    )
    second_session = policy.decide(
        _trace(trace_id="trace-2", session_id="s2", tool_count=1)
    )

    assert not first_session.review_skill
    assert not second_session.review_skill
    assert policy.tool_executions_since_skill == 1


def test_memory_nudge_accumulates_across_sessions_for_same_user() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=2, skill_tool_interval=0)

    first = policy.decide(_trace(trace_id="trace-1", session_id="s1"))
    second = policy.decide(_trace(trace_id="trace-2", session_id="s2"))

    assert not first.review_memory
    assert second.review_memory
    assert policy.turns_since_memory == 2


def test_memory_nudge_is_isolated_by_user() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=2, skill_tool_interval=0)

    first_user = policy.decide(_trace(trace_id="trace-1", user_id="u1"))
    second_user = policy.decide(_trace(trace_id="trace-2", user_id="u2"))

    assert not first_user.review_memory
    assert not second_user.review_memory
    assert policy.turns_since_memory == 1


def test_hydrates_memory_counter_from_all_user_sessions() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=3, skill_tool_interval=0)
    policy.hydrate(
        [
            _trace(trace_id="trace-1", session_id="s1"),
            _trace(trace_id="trace-2", session_id="s2"),
        ],
        session_id="s3",
        user_id="u1",
    )

    decision = policy.decide(_trace(trace_id="trace-3", session_id="s3"))

    assert decision.review_memory


def test_negative_intervals_are_rejected() -> None:
    with pytest.raises(ValueError):
        NudgeReviewTriggerPolicy(memory_turn_interval=-1)
    with pytest.raises(ValueError):
        NudgeReviewTriggerPolicy(skill_tool_interval=-1)


def _trace(
    *,
    trace_id: str,
    session_id: str = "s1",
    user_id: str = "u1",
    status: str = "success",
    final_response: str = "done",
    tool_count: int = 0,
    tool_executions: list[ToolExecutionTrace] | None = None,
) -> RuntimeTrace:
    executions = tool_executions
    if executions is None:
        executions = [_execution("read_file", index=index) for index in range(tool_count)]
    return RuntimeTrace(
        session_id=session_id,
        user_id=user_id,
        user_message="hello",
        final_response=final_response,
        status=status,
        trace_id=trace_id,
        tool_executions=executions,
    )


def _execution(
    tool_name: str,
    *,
    action: str = "",
    status: str = "success",
    index: int = 0,
) -> ToolExecutionTrace:
    return ToolExecutionTrace(
        iteration=index + 1,
        tool_call_id=f"call-{index}-{tool_name}",
        tool_name=tool_name,
        status=status,
        arguments={"action": action} if action else {},
    )
