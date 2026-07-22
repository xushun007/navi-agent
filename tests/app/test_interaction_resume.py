from __future__ import annotations

import tempfile
from pathlib import Path

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.events import RuntimeEvent
from navi_agent.runtime import (
    AgentRuntime,
    DeferredApprovalProvider,
    InMemorySessionStore,
    JsonPendingInteractionStore,
    ModelResponse,
    ToolCall,
    ToolRegistry,
    ToolResult,
)
from navi_agent.runtime.tool_policy import SensitiveToolPolicy
from navi_agent.tools import AskUserTool


class _Transport:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return self._responses.pop(0)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def handle(self, event: RuntimeEvent) -> None:
        self.events.append(event)


def test_approval_executes_checkpoint_without_model_retry() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "pending.json"
        store = JsonPendingInteractionStore(path)
        executions: list[str] = []

        def guarded(value: str) -> ToolResult:
            executions.append(value)
            return ToolResult.ok(name="guarded", content=value)

        transport = _Transport(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(id="tc1", name="guarded", arguments={"value": "once"})
                    ]
                ),
                ModelResponse(content="done"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            session_store=InMemorySessionStore(),
            tool_registry=ToolRegistry(
                tools={"guarded": guarded},
                policy=SensitiveToolPolicy(
                    approval_required_tools={"guarded": "approval required"}
                ),
                approval_provider=DeferredApprovalProvider(store),
            ),
        )
        service = ApplicationService(runtime=runtime, interaction_store=store)

        waiting = service.handle(AppRequest(session_id="s1", user_id="u1", message="run"))
        pending = JsonPendingInteractionStore(path).get_pending("s1")
        assert pending is not None
        assert pending.tool_call_id == "tc1"
        assert executions == []

        assert service.resolve_interaction("s1", approved=True) is not None
        resumed = service.handle(
            AppRequest(session_id="s1", user_id="u1", message="/approve")
        )

    assert waiting.status == "awaiting_input"
    assert resumed.status == "success"
    assert executions == ["once"]
    assert len(transport.calls) == 2
    assert service.resolve_interaction("s1", approved=True) is None
    assert [message.role for message in resumed.messages[-2:]] == ["tool", "assistant"]


def test_denial_continues_without_executing_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = JsonPendingInteractionStore(Path(tmpdir) / "pending.json")
        executions: list[str] = []
        transport = _Transport(
            [
                ModelResponse(
                    tool_calls=[ToolCall(id="tc1", name="guarded", arguments={})]
                ),
                ModelResponse(content="continued without tool"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(
                tools={
                    "guarded": lambda: executions.append("ran")
                    or ToolResult.ok(name="guarded", content="ran")
                },
                policy=SensitiveToolPolicy(
                    approval_required_tools={"guarded": "approval required"}
                ),
                approval_provider=DeferredApprovalProvider(store),
            ),
        )
        service = ApplicationService(runtime=runtime, interaction_store=store)

        service.handle(AppRequest(session_id="s1", user_id="u1", message="run"))
        service.resolve_interaction("s1", approved=False)
        resumed = service.handle(AppRequest(session_id="s1", user_id="u1", message="/deny"))

    assert resumed.status == "success"
    assert executions == []
    assert resumed.messages[-2].role == "tool"
    assert "denied" in resumed.messages[-2].content.lower()


def test_clarification_response_resumes_persisted_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "pending.json"
        store = JsonPendingInteractionStore(path)
        recorder = _Recorder()
        transport = _Transport(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="ask_user",
                            arguments={"question": "Which environment?"},
                        )
                    ]
                ),
                ModelResponse(content="deploying to staging"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(registered_tools=[("interaction", AskUserTool(store))]),
            event_subscribers=[recorder],
        )
        first_service = ApplicationService(runtime=runtime, interaction_store=store)
        first_service.handle(AppRequest(session_id="s1", user_id="u1", message="deploy"))

        restarted_store = JsonPendingInteractionStore(path)
        restarted_service = ApplicationService(
            runtime=runtime,
            interaction_store=restarted_store,
        )
        resumed = restarted_service.handle(
            AppRequest(session_id="s1", user_id="u1", message="staging")
        )

    assert resumed.status == "success"
    assert resumed.messages[-2].role == "tool"
    assert "staging" in resumed.messages[-2].content
    assert any(event.name == "runtime.resumed" for event in recorder.events)
