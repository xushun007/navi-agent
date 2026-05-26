import unittest

from navi_agent.tooling import ToolDecision
from navi_agent.runtime import (
    AgentRuntime,
    InMemorySessionStore,
    ModelRequest,
    ModelResponse,
    PromptBuilder,
    RuntimeEvent,
    ToolArtifact,
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    ToolsetDefinition,
)
from navi_agent.memory import InMemoryMemoryStore, MemoryRecord
from navi_agent.tools import MemoryTool
from navi_agent.telemetry import InMemoryTraceStore


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, request: ModelRequest):
        self.calls.append(request)
        return self._responses.pop(0)


class TrackingPromptBuilder(PromptBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    def build_initial_messages(self, session, user_message, system_prompt=None):
        self.calls.append(
            {
                "session_id": session.session_id,
                "user_message": user_message,
                "system_prompt": system_prompt,
            }
        )
        return super().build_initial_messages(session, user_message, system_prompt)


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def on_event(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class RecordingToolResultRenderer:
    def __init__(self) -> None:
        self.results: list[ToolResult] = []

    def render(self, result: ToolResult) -> str:
        self.results.append(result)
        return f"rendered:{result.name}:{result.status}"


def ok_result(name: str, content: str, **kwargs) -> ToolResult:
    return ToolResult(tool_call_id="", name=name, content=content, **kwargs)


class AgentRuntimeTests(unittest.TestCase):
    def test_runtime_returns_final_model_response(self) -> None:
        transport = FakeTransport([ModelResponse(content="done")])
        runtime = AgentRuntime(transport=transport)

        result = runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.final_response, "done")
        self.assertEqual(result.messages[-1].content, "done")

    def test_runtime_executes_tool_calls_then_continues_loop(self) -> None:
        transport = FakeTransport(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(id="tc1", name="echo", arguments={"value": "ping"})
                    ]
                ),
                ModelResponse(content="tool complete"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(tools={"echo": lambda value: ok_result("echo", f"tool:{value}")}),
        )

        result = runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="run tool",
        )

        self.assertEqual(result.final_response, "tool complete")
        self.assertEqual(
            [(item.name, item.content) for item in result.tool_results],
            [("echo", "tool:ping")],
        )
        self.assertEqual(result.tool_results[0].structured_content, {})
        self.assertEqual(result.messages[-2].role, "tool")
        self.assertEqual(result.messages[-2].content, "tool:ping")

    def test_runtime_persists_message_history_in_session_store(self) -> None:
        session_store = InMemorySessionStore()
        transport = FakeTransport([ModelResponse(content="done")])
        runtime = AgentRuntime(transport=transport, session_store=session_store)

        runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        session = session_store.load(session_id="s1", user_id="u1")
        self.assertEqual([message.role for message in session.messages], ["user", "assistant"])

    def test_runtime_injects_system_prompt_on_first_turn_only(self) -> None:
        session_store = InMemorySessionStore()
        transport = FakeTransport(
            [ModelResponse(content="first"), ModelResponse(content="second")]
        )
        runtime = AgentRuntime(transport=transport, session_store=session_store)

        runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            system_prompt="system",
        )
        runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="again",
            system_prompt="ignored",
        )

        session = session_store.load(session_id="s1", user_id="u1")
        self.assertEqual(
            [message.role for message in session.messages],
            ["system", "user", "assistant", "user", "assistant"],
        )

    def test_runtime_uses_prompt_builder_boundary(self) -> None:
        transport = FakeTransport([ModelResponse(content="done")])
        prompt_builder = TrackingPromptBuilder()
        runtime = AgentRuntime(
            transport=transport,
            prompt_builder=prompt_builder,
        )

        runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            system_prompt="system",
        )

        self.assertEqual(len(prompt_builder.calls), 1)
        self.assertEqual(prompt_builder.calls[0]["user_message"], "hello")
        self.assertEqual(prompt_builder.calls[0]["system_prompt"], "system")

    def test_prompt_builder_includes_memory_in_first_system_message(self) -> None:
        transport = FakeTransport([ModelResponse(content="done")])
        prompt_builder = PromptBuilder(
            memory_store=InMemoryMemoryStore(
                records=[MemoryRecord(user_id="u1", content="Prefers concise replies")]
            )
        )
        runtime = AgentRuntime(
            transport=transport,
            prompt_builder=prompt_builder,
        )

        runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            system_prompt="system",
        )

        request = transport.calls[0]
        self.assertEqual(request.messages[0].role, "system")
        self.assertIn("system", request.messages[0].content)
        self.assertIn("[Memory]", request.messages[0].content)
        self.assertIn("Prefers concise replies", request.messages[0].content)

    def test_runtime_passes_messages_and_tools_through_transport_request(self) -> None:
        transport = FakeTransport([ModelResponse(content="done")])
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(
                definitions=[
                    ToolDefinition(
                        name="echo",
                        description="Echo a value",
                        parameters={
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                        },
                        handler=lambda value: ok_result("echo", value),
                    )
                ]
            ),
        )

        runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            system_prompt="system",
        )

        request = transport.calls[0]
        self.assertEqual([message.role for message in request.messages], ["system", "user"])
        self.assertEqual(
            request.tools,
            [
                {
                    "name": "echo",
                    "description": "Echo a value",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                }
            ],
        )

    def test_runtime_records_trace_on_success(self) -> None:
        transport = FakeTransport([ModelResponse(content="done")])
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=transport,
            trace_store=trace_store,
            tool_registry=ToolRegistry(
                definitions=[
                    ToolDefinition(
                        name="echo",
                        handler=lambda value: ok_result("echo", value),
                    )
                ]
            ),
        )

        runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
        )

        self.assertEqual(len(trace_store.traces), 1)
        trace = trace_store.traces[0]
        self.assertEqual(trace.session_id, "s1")
        self.assertEqual(trace.user_message, "hello")
        self.assertEqual(trace.final_response, "done")
        self.assertEqual(trace.status, "success")

    def test_runtime_emits_structured_events(self) -> None:
        transport = FakeTransport(
            [
                ModelResponse(
                    tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "ping"})]
                ),
                ModelResponse(content="done"),
            ]
        )
        observer = RecordingObserver()
        runtime = AgentRuntime(
            transport=transport,
            observers=[observer],
            tool_registry=ToolRegistry(tools={"echo": lambda value: ok_result("echo", f"tool:{value}")}),
        )

        runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(
            [event.name for event in observer.events],
            [
                "runtime.started",
                "iteration.started",
                "model.responded",
                "tool.executed",
                "iteration.started",
                "model.responded",
                "runtime.completed",
            ],
        )
        self.assertEqual(observer.events[2].metadata["tool_call_count"], 1)
        self.assertEqual(observer.events[3].metadata["tool_name"], "echo")

    def test_runtime_returns_structured_result_when_iteration_limit_is_hit(self) -> None:
        transport = FakeTransport([ModelResponse(tool_calls=[ToolCall(id="tc1", name="echo", arguments={})])])
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=transport,
            trace_store=trace_store,
            max_iterations=1,
            tool_registry=ToolRegistry(tools={"echo": lambda: ok_result("echo", "tool:ok")}),
        )

        result = runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
        )

        self.assertEqual(result.status, "iteration_limit_exceeded")
        self.assertEqual(result.final_response, "")
        self.assertEqual(trace_store.traces[0].status, "iteration_limit_exceeded")

    def test_runtime_converts_tool_failure_into_tool_message(self) -> None:
        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="fail", arguments={})]),
                ModelResponse(content="recovered"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(
                definitions=[ToolDefinition(name="fail", handler=lambda: (_ for _ in ()).throw(RuntimeError("boom")))]
            ),
        )

        result = runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.final_response, "recovered")
        self.assertEqual(result.tool_results[0].status, "error")
        self.assertIn("boom", result.messages[-2].content)

    def test_runtime_limits_exposed_tools_by_enabled_toolsets(self) -> None:
        transport = FakeTransport([ModelResponse(content="done")])
        runtime = AgentRuntime(
            transport=transport,
            enabled_toolsets=["web"],
            tool_registry=ToolRegistry(
                definitions=[
                    ToolDefinition(name="web_search", handler=lambda query: ok_result("web_search", query), toolset="web"),
                    ToolDefinition(name="read_file", handler=lambda path: ok_result("read_file", path), toolset="file"),
                ],
                toolsets=[
                    ToolsetDefinition(name="web", tools=["web_search"]),
                    ToolsetDefinition(name="file", tools=["read_file"]),
                ],
            ),
        )

        runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(
            [tool["name"] for tool in transport.calls[0].tools],
            ["web_search"],
        )

    def test_runtime_passes_tool_context_when_dispatching(self) -> None:
        seen: list[ToolContext] = []

        def inspect(context: ToolContext) -> ToolResult:
            seen.append(context)
            return ok_result("inspect", f"iter:{context.iteration}")

        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="inspect", arguments={})]),
                ModelResponse(content="done"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(
                definitions=[ToolDefinition(name="inspect", handler=inspect, toolset="debug")]
            ),
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(result.tool_results[0].content, "iter:1")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].session_id, "s1")

    def test_memory_tool_updates_prompt_builder_memory_store(self) -> None:
        memory_store = InMemoryMemoryStore()
        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="memory", arguments={"action": "add", "content": "Prefers terse replies"})]),
                ModelResponse(content="stored"),
                ModelResponse(content="next"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            prompt_builder=PromptBuilder(memory_store=memory_store),
            tool_registry=ToolRegistry(
                registered_tools=[("memory", MemoryTool(memory_store=memory_store))]
            ),
        )

        runtime.run_conversation(session_id="s1", user_id="u1", user_message="remember this")
        runtime.run_conversation(session_id="s2", user_id="u1", user_message="hello again", system_prompt="system")

        request = transport.calls[-1]
        self.assertIn("[Memory]", request.messages[0].content)
        self.assertIn("Prefers terse replies", request.messages[0].content)

    def test_runtime_uses_tool_result_renderer_boundary(self) -> None:
        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "ping"})]),
                ModelResponse(content="done"),
            ]
        )
        renderer = RecordingToolResultRenderer()
        runtime = AgentRuntime(
            transport=transport,
            tool_result_renderer=renderer,
            tool_registry=ToolRegistry(
                tools={
                    "echo": lambda value: ToolResult.ok(
                        "echo",
                        "tool:ping",
                        structured_content={"value": value},
                    )
                }
            ),
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(renderer.results[0].structured_content["value"], "ping")
        self.assertEqual(result.messages[-2].content, "rendered:echo:success")

    def test_default_tool_result_renderer_exposes_artifacts(self) -> None:
        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="echo", arguments={})]),
                ModelResponse(content="done"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(
                tools={
                    "echo": lambda: ToolResult.ok(
                        "echo",
                        "",
                        artifacts=[
                            ToolArtifact(
                                kind="file",
                                uri="/tmp/out.txt",
                                title="out.txt",
                            )
                        ],
                    )
                }
            ),
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertIn("Artifacts:", result.messages[-2].content)
        self.assertIn("out.txt", result.messages[-2].content)

    def test_runtime_surfaces_policy_denial_as_tool_message(self) -> None:
        class DenyPolicy:
            def decide(self, tool_name: str, arguments: dict, context: ToolContext | None) -> ToolDecision:
                return ToolDecision.deny("write_file requires approval")

        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="write_file", arguments={"path": "a.txt", "content": "x"})]),
                ModelResponse(content="done"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_registry=ToolRegistry(
                tools={"write_file": lambda path, content: ToolResult.ok("write_file", "written")},
                policy=DenyPolicy(),
            ),
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="write file")

        self.assertEqual(result.tool_results[0].status, "error")
        self.assertIn("requires approval", result.messages[-2].content)


if __name__ == "__main__":
    unittest.main()
