from pathlib import Path

from navi_agent.evolution import FileSkillStore, SkillReviewEvidence, SkillReviewService
from navi_agent.runtime import Message, ModelResponse
from navi_agent.runtime.transports import ModelRequest
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


class FakeTransport:
    def __init__(self, content: str | list[str]) -> None:
        self.contents = [content] if isinstance(content, str) else list(content)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(content=self.contents.pop(0))


def test_llm_review_proposes_skill_candidate(tmp_path: Path) -> None:
    transport = FakeTransport(
        [
            """
            {
              "action": "create_skill",
              "skill_name": "readme-verification",
              "summary": "Create README verification skill",
              "rationale": "The trace shows a reusable read then verify workflow."
            }
            """,
            """
            {
              "skill_name": "readme-verification",
              "summary": "Create README verification skill",
              "rationale": "The trace shows a reusable read then verify workflow.",
              "skill_content": "# README Verification\\n\\n## When To Use\\n\\nUse for README checks.\\n\\n## Procedure\\n\\n- Read README.\\n- Verify result.\\n\\n## Evidence\\n\\n- session trace."
            }
            """,
        ]
    )

    candidate = SkillReviewService(
        transport=transport,
        skill_store=FileSkillStore(tmp_path),
    ).propose_candidate(_tool_trace())

    assert candidate is not None
    assert candidate.target == "skill"
    assert candidate.metadata["reviewer"] == "llm"
    assert candidate.metadata["skill_name"] == "readme-verification"
    assert "## Procedure" in candidate.metadata["skill_content"]
    assert len(transport.requests) == 2


def test_llm_review_skips_nothing_decision(tmp_path: Path) -> None:
    transport = FakeTransport(
        '{"action": "nothing", "skill_name": "", "summary": "", "rationale": "one-off", "skill_content": ""}'
    )

    candidate = SkillReviewService(
        transport=transport,
        skill_store=FileSkillStore(tmp_path),
    ).propose_candidate(_tool_trace())

    assert candidate is None
    assert len(transport.requests) == 1


def test_llm_review_skips_existing_skill(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-verification",
        content="# README Verification\n\n## When To Use\n\nUse for README checks.",
    )
    transport = FakeTransport(
        """
        {
          "action": "create_skill",
          "skill_name": "readme-verification",
          "summary": "Duplicate",
          "rationale": "Duplicate",
          "skill_content": "# Duplicate\\n\\n## When To Use\\n\\nUse.\\n\\n## Procedure\\n\\n- Do.\\n\\n## Evidence\\n\\n- Trace."
        }
        """
    )

    candidate = SkillReviewService(
        transport=transport,
        skill_store=store,
    ).propose_candidate(_tool_trace())

    assert candidate is None
    assert len(transport.requests) == 1


def test_llm_review_proposes_update_skill_candidate(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-verification",
        content="# README Verification\n\n## When To Use\n\nUse for README checks.",
    )
    transport = FakeTransport(
        [
            """
            {
              "action": "update_skill",
              "skill_name": "readme-verification",
              "summary": "Update README verification skill",
              "rationale": "The trace adds a verification step."
            }
            """,
            """
            {
              "summary": "Update README verification skill",
              "rationale": "The trace adds a verification step.",
              "section": "## Procedure",
              "append_content": "- Verify tests."
            }
            """,
        ]
    )

    candidate = SkillReviewService(
        transport=transport,
        skill_store=store,
    ).propose_candidate(_tool_trace())

    assert candidate is not None
    assert candidate.metadata["operation"] == "update"
    assert candidate.metadata["skill_name"] == "readme-verification"
    assert candidate.metadata["section"] == "## Procedure"
    assert candidate.metadata["append_content"] == "- Verify tests."
    assert len(transport.requests) == 2


def test_llm_review_invalid_response_returns_none(tmp_path: Path) -> None:
    candidate = SkillReviewService(
        transport=FakeTransport("not json"),
        skill_store=FileSkillStore(tmp_path),
    ).propose_candidate(_tool_trace())

    assert candidate is None


def test_skill_review_prompt_discourages_micro_skills(tmp_path: Path) -> None:
    transport = FakeTransport(
        '{"action": "nothing", "skill_name": "", "summary": "", "rationale": "one-off", "skill_content": ""}'
    )

    SkillReviewService(
        transport=transport,
        skill_store=FileSkillStore(tmp_path),
    ).propose_candidate(_tool_trace())

    system_prompt = transport.requests[0].messages[0].content
    assert "not one-session micro skills" in system_prompt
    assert "one exact error string" in system_prompt
    assert "update the broadest one" in system_prompt


def test_update_prompt_is_append_only(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-verification",
        content="# README Verification\n\n## When To Use\n\nUse for README checks.",
    )
    transport = FakeTransport(
        [
            """
            {
              "action": "update_skill",
              "skill_name": "readme-verification",
              "summary": "Update README verification skill",
              "rationale": "The trace adds a verification step."
            }
            """,
            """
            {
              "summary": "Update README verification skill",
              "rationale": "The trace adds a verification step.",
              "section": "## Procedure",
              "append_content": "- Verify tests."
            }
            """,
        ]
    )

    SkillReviewService(
        transport=transport,
        skill_store=store,
    ).propose_candidate(_tool_trace())

    system_prompt = transport.requests[1].messages[0].content
    assert "Never rewrite the full SKILL.md" in system_prompt
    assert "append_content" in system_prompt


def test_planning_prompt_uses_skill_summaries_without_full_content(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-verification",
        content=(
            "# README Verification\n\n"
            "## When To Use\n\nUse for README checks.\n\n"
            "## Procedure\n\n- SECRET_LONG_CONTENT_SHOULD_NOT_BE_IN_PLANNING"
        ),
    )
    transport = FakeTransport(
        [
            """
            {
              "action": "update_skill",
              "skill_name": "readme-verification",
              "summary": "Update README verification skill",
              "rationale": "The trace adds a verification step."
            }
            """,
            """
            {
              "summary": "Update README verification skill",
              "rationale": "The trace adds a verification step.",
              "section": "## Procedure",
              "append_content": "- Verify tests."
            }
            """,
        ]
    )

    SkillReviewService(
        transport=transport,
        skill_store=store,
    ).propose_candidate(_tool_trace())

    planning_prompt = transport.requests[0].messages[1].content
    update_prompt = transport.requests[1].messages[1].content
    assert "SECRET_LONG_CONTENT_SHOULD_NOT_BE_IN_PLANNING" not in planning_prompt
    assert "SECRET_LONG_CONTENT_SHOULD_NOT_BE_IN_PLANNING" in update_prompt


def test_review_accepts_multi_trace_evidence_window(tmp_path: Path) -> None:
    transport = FakeTransport(
        [
            """
            {
              "action": "create_skill",
              "skill_name": "readme-verification",
              "summary": "Create README verification skill",
              "rationale": "The evidence shows a reusable read then verify workflow."
            }
            """,
            """
            {
              "skill_name": "readme-verification",
              "summary": "Create README verification skill",
              "rationale": "The evidence shows a reusable read then verify workflow.",
              "skill_content": "# README Verification\\n\\n## When To Use\\n\\nUse for README checks.\\n\\n## Procedure\\n\\n- Read README.\\n- Verify result.\\n\\n## Evidence\\n\\n- multi-trace evidence."
            }
            """,
        ]
    )
    first = _tool_trace(trace_id="trace-1", user_message="Read README")
    second = _tool_trace(trace_id="trace-2", user_message="Verify README")

    candidate = SkillReviewService(
        transport=transport,
        skill_store=FileSkillStore(tmp_path),
    ).propose_candidate(
        SkillReviewEvidence(
            traces=[first, second],
            messages_snapshot=[
                Message(role="user", content="Read README"),
                Message(role="assistant", content="Done."),
                Message(role="user", content="Verify README"),
                Message(role="assistant", content="Done."),
            ],
        )
    )

    assert candidate is not None
    assert candidate.metadata["source_trace_id"] == "trace-2"
    assert candidate.metadata["source_trace_ids"] == ["trace-1", "trace-2"]
    planning_prompt = transport.requests[0].messages[1].content
    assert "## Message 1" in planning_prompt
    assert "Read README" in planning_prompt
    assert "## Message 3" in planning_prompt
    assert "Verify README" in planning_prompt


def _tool_trace(
    *,
    trace_id: str = "trace-1",
    user_message: str = "Read README and verify the project goal",
) -> RuntimeTrace:
    return RuntimeTrace(
        session_id="session-1",
        user_id="user-1",
        user_message=user_message,
        final_response="Done.",
        status="success",
        trace_id=trace_id,
        tool_executions=[
            ToolExecutionTrace(
                iteration=1,
                tool_call_id="call-1",
                tool_name="read_file",
                status="success",
                content="README content",
            )
        ],
    )
