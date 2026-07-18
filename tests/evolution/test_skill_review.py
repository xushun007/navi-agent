from pathlib import Path

from navi_agent.evolution import FileSkillStore, SkillReviewService
from navi_agent.runtime import ModelResponse
from navi_agent.runtime.transports import ModelRequest
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


class FakeTransport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(content=self.content)


def test_llm_review_proposes_skill_candidate(tmp_path: Path) -> None:
    transport = FakeTransport(
        """
        {
          "action": "create_skill",
          "skill_name": "readme-verification",
          "summary": "Create README verification skill",
          "rationale": "The trace shows a reusable read then verify workflow.",
          "skill_content": "# README Verification\\n\\n## When To Use\\n\\nUse for README checks.\\n\\n## Procedure\\n\\n- Read README.\\n- Verify result.\\n\\n## Evidence\\n\\n- session trace."
        }
        """
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
    assert len(transport.requests) == 1


def test_llm_review_skips_nothing_decision(tmp_path: Path) -> None:
    transport = FakeTransport(
        '{"action": "nothing", "skill_name": "", "summary": "", "rationale": "one-off", "skill_content": ""}'
    )

    candidate = SkillReviewService(
        transport=transport,
        skill_store=FileSkillStore(tmp_path),
    ).propose_candidate(_tool_trace())

    assert candidate is None


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


def test_llm_review_invalid_response_returns_none(tmp_path: Path) -> None:
    candidate = SkillReviewService(
        transport=FakeTransport("not json"),
        skill_store=FileSkillStore(tmp_path),
    ).propose_candidate(_tool_trace())

    assert candidate is None


def _tool_trace() -> RuntimeTrace:
    return RuntimeTrace(
        session_id="session-1",
        user_id="user-1",
        user_message="Read README and verify the project goal",
        final_response="Done.",
        status="success",
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
