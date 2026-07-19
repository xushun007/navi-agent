from navi_agent.evolution import SkillReviewEvidence, render_skill_review_evidence
from navi_agent.runtime import Message, ToolCall
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


def test_render_skill_review_evidence_prefers_raw_messages_snapshot() -> None:
    long_tool_output = "start\n" + ("middle\n" * 200) + "FAILED tests/test_core.py\nAssertionError: boom"
    evidence = SkillReviewEvidence(
        traces=[_trace_with_tool_output("trace output should not be used when messages exist")],
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


def test_render_skill_review_evidence_falls_back_to_full_trace_evidence() -> None:
    output = "pytest start\n" + ("middle\n" * 200) + "FAILED tests/test_core.py::test_core\nAssertionError: boom"
    evidence = SkillReviewEvidence(
        traces=[
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="Run tests",
                final_response="Tests failed.",
                status="success",
                trace_id="trace-1",
                tool_executions=[
                    ToolExecutionTrace(
                        iteration=1,
                        tool_call_id="call-1",
                        tool_name="bash",
                        status="error",
                        arguments={"command": "uv run pytest tests/test_core.py"},
                        content=output,
                        error_category="timeout",
                        error_type="TimeoutError",
                        error_message="command timed out after 30 seconds",
                        retryable=True,
                    )
                ],
            )
        ]
    )

    rendered = render_skill_review_evidence(evidence)

    assert "tool: bash" in rendered
    assert '"command": "uv run pytest tests/test_core.py"' in rendered
    assert "error: category=timeout type=TimeoutError retryable=True" in rendered
    assert "pytest start" in rendered
    assert "FAILED tests/test_core.py::test_core" in rendered
    assert "AssertionError: boom" in rendered
    assert "[truncated" not in rendered


def test_render_skill_review_evidence_includes_http_error_metadata() -> None:
    evidence = SkillReviewEvidence(
        traces=[
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="Call API",
                final_response="Rate limited.",
                status="success",
                trace_id="trace-1",
                tool_executions=[
                    ToolExecutionTrace(
                        iteration=1,
                        tool_call_id="call-1",
                        tool_name="web_api",
                        status="error",
                        arguments={"url": "https://api.example.test"},
                        content="429 Too Many Requests",
                        error_category="rate_limit",
                        error_type="HTTPError",
                        http_status=429,
                        retryable=True,
                    )
                ],
            )
        ]
    )

    rendered = render_skill_review_evidence(evidence)

    assert "http_status=429" in rendered
    assert "retryable=True" in rendered


def _trace_with_tool_output(content: str) -> RuntimeTrace:
    return RuntimeTrace(
        session_id="s1",
        user_id="u1",
        user_message="Run tests",
        final_response="Tests failed.",
        status="success",
        trace_id="trace-1",
        tool_executions=[
            ToolExecutionTrace(
                iteration=1,
                tool_call_id="call-1",
                tool_name="bash",
                status="error",
                content=content,
            )
        ],
    )
