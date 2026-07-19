from pathlib import Path

from navi_agent.evolution import FileSkillStore, SkillReviewAgentService, SkillReviewEvidence
from navi_agent.runtime import ModelRequest, ModelResponse, ToolCall
from navi_agent.telemetry import RuntimeTrace, ToolExecutionTrace


class ScriptedTransport:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def test_skill_review_agent_creates_skill_via_tool(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    transport = ScriptedTransport(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-list",
                        name="skill_manage",
                        arguments={"action": "list"},
                    )
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-create",
                        name="skill_manage",
                        arguments={
                            "action": "create",
                            "skill_name": "readme-verification",
                            "skill_content": (
                                "# README Verification\n\n"
                                "## When To Use\n\nUse for README checks.\n\n"
                                "## Procedure\n\n- Read README.\n- Verify the result.\n\n"
                                "## Evidence\n\n- Created from review evidence."
                            ),
                        },
                    )
                ]
            ),
            ModelResponse(content="Skill updated."),
        ]
    )

    result = SkillReviewAgentService(
        transport=transport,
        skill_store=store,
    ).review_and_write(SkillReviewEvidence(traces=[_tool_trace()]))

    record = store.get("readme-verification")
    assert result.status == "success"
    assert record is not None
    assert "Verify the result" in record.content
    assert [item.name for item in result.tool_results] == ["skill_manage", "skill_manage"]
    assert result.tool_results[1].structured_content["action"] == "create"


def test_skill_review_agent_appends_existing_skill_via_tool(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-verification",
        content="# README Verification\n\n## Procedure\n\n- Read README.",
    )
    transport = ScriptedTransport(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-list",
                        name="skill_manage",
                        arguments={"action": "list"},
                    )
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-view",
                        name="skill_manage",
                        arguments={"action": "view", "skill_name": "readme-verification"},
                    )
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-append",
                        name="skill_manage",
                        arguments={
                            "action": "append",
                            "skill_name": "readme-verification",
                            "section": "## Procedure",
                            "append_content": "- Verify the result before replying.",
                        },
                    )
                ]
            ),
            ModelResponse(content="Skill updated."),
        ]
    )

    result = SkillReviewAgentService(
        transport=transport,
        skill_store=store,
    ).review_and_write(SkillReviewEvidence(traces=[_tool_trace()]))

    record = store.get("readme-verification")
    assert result.status == "success"
    assert record is not None
    assert "- Read README." in record.content
    assert "- Verify the result before replying." in record.content
    assert result.tool_results[-1].structured_content["action"] == "append"


def _tool_trace() -> RuntimeTrace:
    return RuntimeTrace(
        session_id="session-1",
        user_id="user-1",
        user_message="Read README and verify the project goal",
        final_response="Done.",
        status="success",
        trace_id="trace-1",
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
