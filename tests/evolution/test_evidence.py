from navi_agent.evolution import SkillReviewEvidence, render_skill_review_evidence
from navi_agent.runtime import Message, ToolCall


def test_render_skill_review_evidence_prefers_raw_messages_snapshot() -> None:
    long_tool_output = "start\n" + ("middle\n" * 200) + "FAILED tests/test_core.py\nAssertionError: boom"
    evidence = SkillReviewEvidence(
        session_id="s1",
        trace_id="trace-1",
        user_id="u1",
        messages_snapshot=[
            Message(role="user", content="Run tests"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="bash",
                        arguments={"command": "uv run pytest tests/test_core.py"},
                    )
                ],
            ),
            Message(
                role="tool",
                tool_call_id="call-1",
                content=long_tool_output,
            ),
            Message(role="assistant", content="Tests failed."),
        ],
    )

    rendered = render_skill_review_evidence(evidence)

    assert "## Message 1" in rendered
    assert "role: user" in rendered
    assert '"command": "uv run pytest tests/test_core.py"' in rendered
    assert "start" in rendered
    assert "FAILED tests/test_core.py" in rendered
    assert "AssertionError: boom" in rendered
    assert "trace output should not be used" not in rendered
    assert "[truncated" not in rendered


def test_render_skill_review_evidence_requires_messages_snapshot() -> None:
    evidence = SkillReviewEvidence(
        session_id="s1",
        trace_id="trace-1",
        user_id="u1",
        messages_snapshot=[],
    )

    rendered = render_skill_review_evidence(evidence)

    assert rendered == ""


def test_render_skill_review_evidence_does_not_mix_trace_metadata() -> None:
    evidence = SkillReviewEvidence(
        session_id="s1",
        trace_id="trace-1",
        user_id="u1",
        messages_snapshot=[
            Message(role="tool", tool_call_id="call-1", content="429 Too Many Requests")
        ],
    )

    rendered = render_skill_review_evidence(evidence)

    assert "429 Too Many Requests" in rendered
    assert "http_status=429" not in rendered
    assert "retryable=True" not in rendered
