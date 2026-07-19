from navi_agent.evolution import SkillReviewEvidence, render_skill_review_evidence, smart_truncate
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


def test_smart_truncate_preserves_tail() -> None:
    text = "HEAD-" + ("x" * 1000) + "-TAIL-STACKTRACE"

    rendered = smart_truncate(text, limit=120, head=40, tail=60)

    assert rendered.startswith("HEAD-")
    assert "[truncated" in rendered
    assert rendered.endswith("-TAIL-STACKTRACE")


def test_render_skill_review_evidence_includes_arguments_and_error_tail() -> None:
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
    assert "[truncated" in rendered


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
