from pathlib import Path

from navi_agent.evolution import (
    EvolutionCandidate,
    FileSkillStore,
    ReviewAgentService,
    SkillProvenanceStore,
    SkillReviewEvidence,
)
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.runtime import Message, ModelRequest, ModelResponse, ToolCall


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
                                "---\n"
                                "name: readme-verification\n"
                                "description: Verify README changes.\n"
                                "category: coding\n"
                                "---\n\n"
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

    result = ReviewAgentService(
        transport=transport,
        memory_store=InMemoryMemoryStore(),
        skill_store=store,
    ).review_and_write(
        evidence=SkillReviewEvidence(
            session_id="session-1",
            trace_id="trace-1",
            user_id="user-1",
            messages_snapshot=[Message(role="user", content="Read README")],
        ),
        review_memory=False,
        review_skill=True,
    )

    assert result.status == "success"
    assert store.get("readme-verification") is None
    assert [item.name for item in result.tool_results] == ["skill_manage", "skill_manage"]
    assert result.tool_results[1].structured_content["action"] == "draft_create"
    assert result.tool_results[1].structured_content["admission_status"] == "candidate"


def test_skill_review_agent_appends_existing_skill_via_tool(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-verification",
        content=(
            "---\n"
            "name: readme-verification\n"
            "description: Verify README changes.\n"
            "category: coding\n"
            "---\n\n"
            "# README Verification\n\n"
            "## When To Use\n\nUse for README checks.\n\n"
            "## Procedure\n\n- Read README."
        ),
    )
    provenance_store = SkillProvenanceStore(tmp_path)
    provenance_store.mark_agent_created(
        skill_name="readme-verification",
        candidate=EvolutionCandidate(target="skill", summary="created", rationale="review"),
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

    result = ReviewAgentService(
        transport=transport,
        memory_store=InMemoryMemoryStore(),
        skill_store=store,
        skill_provenance_store=provenance_store,
    ).review_and_write(
        evidence=SkillReviewEvidence(
            session_id="session-1",
            trace_id="trace-1",
            user_id="user-1",
            messages_snapshot=[Message(role="user", content="Read README")],
        ),
        review_memory=False,
        review_skill=True,
    )

    assert result.status == "success"
    record = store.get("readme-verification")
    assert record is not None
    assert "- Verify the result before replying." not in record.content
    assert result.tool_results[-1].structured_content["action"] == "draft_append"
    assert result.tool_results[-1].structured_content["admission_status"] == "candidate"


def test_skill_review_agent_cannot_append_user_owned_skill(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    original = (
        "---\n"
        "name: readme-verification\n"
        "description: Verify README changes.\n"
        "category: coding\n"
        "---\n\n"
        "# README Verification\n\n"
        "## When To Use\n\nUse for README checks.\n\n"
        "## Procedure\n\n- Keep the user-authored procedure."
    )
    store.create(name="readme-verification", content=original)
    transport = ScriptedTransport(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-append",
                        name="skill_manage",
                        arguments={
                            "action": "append",
                            "skill_name": "readme-verification",
                            "section": "## Procedure",
                            "append_content": "- Background review mutation.",
                        },
                    )
                ]
            ),
            ModelResponse(content="Protected skill left unchanged."),
        ]
    )

    result = ReviewAgentService(
        transport=transport,
        memory_store=InMemoryMemoryStore(),
        skill_store=store,
        skill_provenance_store=SkillProvenanceStore(tmp_path),
    ).review_and_write(
        evidence=SkillReviewEvidence(
            session_id="session-1",
            trace_id="trace-1",
            user_id="user-1",
            messages_snapshot=[Message(role="user", content="Review README")],
        ),
        review_memory=False,
        review_skill=True,
    )

    assert store.get("readme-verification").content == original
    assert result.tool_results[0].status == "error"
    assert result.tool_results[0].structured_content["protected"] is True


def test_skill_review_agent_prompt_contains_arguments_and_error_tail(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    output = "start\n" + ("middle\n" * 200) + "FAILED tests/test_skill.py\nAssertionError: tail"
    transport = ScriptedTransport([ModelResponse(content="Nothing to save.")])
    evidence = SkillReviewEvidence(
        session_id="session-1",
        trace_id="trace-1",
        user_id="user-1",
        messages_snapshot=[
            Message(role="user", content="Run tests"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="bash",
                        arguments={"command": "uv run pytest tests/test_skill.py"},
                    )
                ],
            ),
            Message(role="tool", tool_call_id="call-1", content=output),
            Message(role="assistant", content="Tests failed."),
        ],
    )

    ReviewAgentService(
        transport=transport,
        memory_store=InMemoryMemoryStore(),
        skill_store=store,
    ).review_and_write(evidence, review_memory=False, review_skill=True)

    prompt = transport.requests[0].messages[-1].content
    assert '"command": "uv run pytest tests/test_skill.py"' in prompt
    assert "FAILED tests/test_skill.py" in prompt
    assert "AssertionError: tail" in prompt


def test_review_agent_stores_memory_via_tool(tmp_path: Path) -> None:
    memory_store = InMemoryMemoryStore()
    transport = ScriptedTransport(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(id="call-list", name="memory", arguments={"action": "list"}),
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-add",
                        name="memory",
                        arguments={
                            "action": "add",
                            "target": "user",
                            "kind": "preference",
                            "content": "用户喜欢简洁直接的技术回答。",
                        },
                    )
                ]
            ),
            ModelResponse(content="Memory updated."),
        ]
    )

    result = ReviewAgentService(
        transport=transport,
        memory_store=memory_store,
        skill_store=FileSkillStore(tmp_path),
    ).review_and_write(
        evidence=SkillReviewEvidence(
            session_id="session-1",
            trace_id="trace-1",
            user_id="user-1",
            messages_snapshot=[Message(role="user", content="记住：我喜欢简洁直接的技术回答")],
        ),
        review_memory=True,
        review_skill=False,
    )

    records = memory_store.list_for_user("user-1")
    assert result.status == "success"
    assert len(records) == 1
    assert records[0].kind == "preference"
    assert records[0].target == "user"
    assert records[0].content == "用户喜欢简洁直接的技术回答。"
    assert [item.name for item in result.tool_results] == ["memory", "memory"]
    audit = memory_store.audit_for_user("user-1")
    assert audit[0].source_session_id == "session-1"
    assert audit[0].source_trace_id == "trace-1"
    assert audit[0].review_run_id


def test_review_agent_prompt_defines_memory_skill_boundary(tmp_path: Path) -> None:
    transport = ScriptedTransport([ModelResponse(content="Nothing to save.")])

    ReviewAgentService(
        transport=transport,
        memory_store=InMemoryMemoryStore(),
        skill_store=FileSkillStore(tmp_path),
    ).review_and_write(
        evidence=SkillReviewEvidence(
            session_id="session-1",
            trace_id="trace-1",
            user_id="user-1",
            messages_snapshot=[Message(role="user", content="我喜欢简洁回答，也要记住测试流程")],
        ),
        review_memory=True,
        review_skill=True,
    )

    system_prompt = transport.requests[0].messages[0].content
    user_prompt = transport.requests[0].messages[-1].content
    assert "Decision boundary:" in system_prompt
    assert "memory target=user" in system_prompt
    assert "memory target=memory" in system_prompt
    assert "Use skill_manage for reusable procedures" in system_prompt
    assert "Do not store tool logs" in system_prompt
    assert "Do not store reusable tool procedures as memory" in system_prompt
    assert "Existing user-authored skills are protected" in system_prompt
    assert "- Memory: extract durable user facts" in user_prompt
    assert "- Skills: extract reusable procedures" in user_prompt
