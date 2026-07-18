import pytest

from navi_agent.evolution import NudgeReviewTriggerPolicy
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


def test_memory_nudge_counts_successful_turns() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=2, skill_tool_interval=0)

    first = policy.decide(_trace())
    second = policy.decide(_trace())

    assert not first.should_review
    assert second.review_memory
    assert not second.review_skill
    assert second.reasons == ["memory_nudge_counter"]
    assert policy.turns_since_memory == 0


def test_skill_nudge_counts_tool_executions() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=3)

    first = policy.decide(_trace(tool_count=2))
    second = policy.decide(_trace(tool_count=1))

    assert not first.should_review
    assert second.review_skill
    assert not second.review_memory
    assert second.reasons == ["skill_nudge_counter"]
    assert policy.tool_executions_since_skill == 0


def test_failed_trace_does_not_increment_nudges() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=1, skill_tool_interval=1)

    decision = policy.decide(_trace(status="failed", final_response=""))

    assert not decision.should_review
    assert policy.turns_since_memory == 0
    assert policy.tool_executions_since_skill == 0


def test_memory_nudge_does_not_count_when_memory_unavailable() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=1, skill_tool_interval=0)

    decision = policy.decide(_trace(), memory_available=False)

    assert not decision.should_review
    assert policy.turns_since_memory == 0


def test_memory_tool_execution_resets_memory_nudge() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=2, skill_tool_interval=0)
    policy.decide(_trace())

    decision = policy.decide(_trace(tool_names=["memory"]))

    assert not decision.should_review
    assert policy.turns_since_memory == 0


def test_skill_nudge_does_not_count_when_skill_unavailable() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=1)

    decision = policy.decide(_trace(tool_count=1), skill_available=False)

    assert not decision.should_review
    assert policy.tool_executions_since_skill == 0


def test_skill_manage_execution_resets_skill_nudge() -> None:
    policy = NudgeReviewTriggerPolicy(memory_turn_interval=0, skill_tool_interval=3)
    policy.decide(_trace(tool_count=2))

    decision = policy.decide(_trace(tool_names=["skill_manage"]))

    assert not decision.should_review
    assert policy.tool_executions_since_skill == 0


def test_negative_intervals_are_rejected() -> None:
    with pytest.raises(ValueError):
        NudgeReviewTriggerPolicy(memory_turn_interval=-1)
    with pytest.raises(ValueError):
        NudgeReviewTriggerPolicy(skill_tool_interval=-1)


def _trace(
    *,
    status: str = "success",
    final_response: str = "done",
    tool_count: int = 0,
    tool_names: list[str] | None = None,
) -> RuntimeTrace:
    names = tool_names or ["read_file"] * tool_count
    return RuntimeTrace(
        session_id="s1",
        user_id="u1",
        user_message="hello",
        final_response=final_response,
        status=status,
        tool_executions=[
            ToolExecutionTrace(
                iteration=index + 1,
                tool_call_id=f"call-{index}",
                tool_name=tool_name,
                status="success",
            )
            for index, tool_name in enumerate(names)
        ],
    )
