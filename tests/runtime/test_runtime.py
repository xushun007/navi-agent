import tempfile
import unittest
from pathlib import Path

from navi_agent.tooling import ToolDecision
from navi_agent.evolution import FileSkillStore
from navi_agent.runtime import (
    AgentRuntime,
    ContextEngine,
    InMemorySessionStore,
    LLMContextSummarizer,
    Message,
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
from navi_agent.tools import BashTool, MemoryTool
from navi_agent.telemetry import InMemoryRuntimeEventStore, InMemoryTraceStore


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, request: ModelRequest):
        self.calls.append(request)
        return self._responses.pop(0)


class InterruptingTransport:
    def generate(self, request: ModelRequest):
        raise KeyboardInterrupt()


class FailingTransport:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = []

    def generate(self, request: ModelRequest):
        self.calls.append(request)
        raise self.exc


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


class EmptyToolResultRenderer:
    def render(self, result: ToolResult) -> str:
        return "   "


class FailingContextEngine:
    def build(self, messages):
        raise TimeoutError("summary timeout")


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

    def test_runtime_records_append_only_action_observation_events(self) -> None:
        event_store = InMemoryRuntimeEventStore()
        transport = FakeTransport(
            [
                ModelResponse(
                    tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "ping"})]
                ),
                ModelResponse(content="done"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            event_store=event_store,
            tool_registry=ToolRegistry(
                tools={"echo": lambda value: ok_result("echo", f"tool:{value}")}
            ),
        )

        result = runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="hello",
        )

        events = event_store.list_events(session_id="s1")
        self.assertEqual(result.status, "success")
        self.assertEqual(
            [event.name for event in events],
            [
                "runtime.started",
                "user.message",
                "model.response",
                "tool.result",
                "model.response",
                "runtime.completed",
            ],
        )
        self.assertEqual([event.sequence for event in events], [1, 2, 3, 4, 5, 6])
        self.assertEqual(events[1].kind, "action")
        self.assertEqual(events[1].source, "user")
        self.assertEqual(events[3].kind, "observation")
        self.assertEqual(events[3].source, "tool")
        self.assertEqual(events[3].payload["tool_name"], "echo")
        self.assertEqual(events[5].payload["status"], "success")

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
        self.assertEqual([message.role for message in session.messages], ["system", "user", "assistant"])

    def test_runtime_uses_compressed_context_for_model_request(self) -> None:
        session_store = InMemorySessionStore()
        session = session_store.load(session_id="s1", user_id="u1")
        for index in range(6):
            session_store.append(session, Message(role="user", content=f"old user {index}"))
            session_store.append(session, Message(role="assistant", content=f"old assistant {index}"))
        transport = FakeTransport(
            [
                ModelResponse(content="[Context Summary]\nold turns summarized by llm"),
                ModelResponse(content="done"),
            ]
        )
        observer = RecordingObserver()
        runtime = AgentRuntime(
            transport=transport,
            session_store=session_store,
            context_engine=ContextEngine(
                context_limit_tokens=160,
                reserved_output_tokens=20,
                compression_threshold_ratio=0.5,
                protect_first_messages=1,
                tail_budget_ratio=0.1,
                summarizer=LLMContextSummarizer(transport),
            ),
            observers=[observer],
        )

        result = runtime.run_conversation(
            session_id="s1",
            user_id="u1",
            user_message="new request",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0].tools, [])
        self.assertIn("Historical middle conversation", transport.calls[0].messages[-1].content)
        self.assertLess(len(transport.calls[1].messages), len(result.messages))
        self.assertTrue(any("[Context Summary]" in message.content for message in transport.calls[1].messages))
        self.assertTrue(any("old turns summarized by llm" in message.content for message in transport.calls[1].messages))
        self.assertEqual(result.messages[-2].content, "new request")
        self.assertTrue(any(event.name == "context.compressed" for event in observer.events))
        compression_events = [event for event in observer.events if event.name == "context.compressed"]
        self.assertIn("estimated_tokens_before", compression_events[0].metadata)
        self.assertEqual(compression_events[0].metadata["summary_status"], "llm")

    def test_runtime_continues_when_context_build_fails(self) -> None:
        transport = FakeTransport([ModelResponse(content="done")])
        observer = RecordingObserver()
        runtime = AgentRuntime(
            transport=transport,
            context_engine=FailingContextEngine(),
            observers=[observer],
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.final_response, "done")
        self.assertEqual(transport.calls[0].messages[-1].content, "hello")
        context_failed_events = [event for event in observer.events if event.name == "context.failed"]
        self.assertEqual(len(context_failed_events), 1)
        self.assertEqual(context_failed_events[0].metadata["error_category"], "retryable")
        self.assertEqual(context_failed_events[0].metadata["error_source"], "context")

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
                records=[
                    MemoryRecord(id="m1", user_id="u1", kind="preference", content="Prefers concise replies")
                ]
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
        self.assertEqual(trace.total_iterations, 1)
        self.assertTrue(trace.trace_id)
        self.assertIsNotNone(trace.started_at)
        self.assertIsNotNone(trace.completed_at)
        self.assertGreaterEqual(trace.duration_ms, 0)
        self.assertEqual(trace.model_calls[0].response_content, "done")
        self.assertIsNotNone(trace.model_calls[0].started_at)
        self.assertIsNotNone(trace.model_calls[0].completed_at)
        self.assertGreaterEqual(trace.model_calls[0].duration_ms, 0)

    def test_runtime_does_not_record_skill_index_as_injected_skill_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_store = FileSkillStore(Path(tmpdir))
            skill_store.create(
                name="readme-summary",
                content="\n".join(
                    [
                        "---",
                        "description: Summarize README files",
                        "---",
                    ]
                ),
            )
            transport = FakeTransport([ModelResponse(content="done")])
            trace_store = InMemoryTraceStore()
            runtime = AgentRuntime(
                transport=transport,
                trace_store=trace_store,
                prompt_builder=PromptBuilder(skill_store=skill_store),
            )

            runtime.run_conversation(
                session_id="s1",
                user_id="u1",
                user_message="summarize README",
            )

        self.assertEqual(trace_store.traces[0].injected_skill_names, [])

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

    def test_runtime_records_tool_execution_trace_details(self) -> None:
        transport = FakeTransport(
            [
                ModelResponse(
                    tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "ping"})]
                ),
                ModelResponse(content="done"),
            ]
        )
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=transport,
            trace_store=trace_store,
            tool_registry=ToolRegistry(tools={"echo": lambda value: ok_result("echo", f"tool:{value}")}),
        )

        runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        trace = trace_store.traces[0]
        self.assertEqual(trace.tool_executions[0].tool_name, "echo")
        self.assertEqual(trace.tool_executions[0].arguments["value"], "ping")
        self.assertEqual(trace.tool_executions[0].content, "tool:ping")
        self.assertIsNotNone(trace.tool_executions[0].started_at)
        self.assertIsNotNone(trace.tool_executions[0].completed_at)
        self.assertGreaterEqual(trace.tool_executions[0].duration_ms, 0)

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
        self.assertEqual(trace_store.traces[0].error_source, "runtime")
        self.assertEqual(trace_store.traces[0].error_type, "IterationLimitExceeded")

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

    def test_runtime_does_not_swallow_keyboard_interrupt(self) -> None:
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=InterruptingTransport(),
            trace_store=trace_store,
        )

        with self.assertRaises(KeyboardInterrupt):
            runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(trace_store.traces, [])

    def test_runtime_returns_readable_response_when_retryable_model_failure_occurs(self) -> None:
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=FailingTransport(TimeoutError("model timeout")),
            trace_store=trace_store,
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(result.status, "failed")
        self.assertIn("模型服务暂时不可用", result.final_response)
        self.assertIn("TimeoutError", result.final_response)
        self.assertEqual(result.messages[-1].role, "assistant")
        self.assertEqual(result.messages[-1].content, result.final_response)
        self.assertTrue(trace_store.traces[0].retryable)
        self.assertEqual(trace_store.traces[0].error_type, "TimeoutError")
        self.assertEqual(trace_store.traces[0].error_source, "model")

    def test_runtime_returns_readable_response_when_fatal_model_failure_occurs(self) -> None:
        trace_store = InMemoryTraceStore()
        runtime = AgentRuntime(
            transport=FailingTransport(ValueError("bad request")),
            trace_store=trace_store,
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(result.status, "failed")
        self.assertIn("模型服务调用失败", result.final_response)
        self.assertIn("ValueError", result.final_response)
        self.assertFalse(trace_store.traces[0].retryable)
        self.assertEqual(trace_store.traces[0].error_type, "ValueError")
        self.assertEqual(trace_store.traces[0].error_source, "model")

    def test_runtime_classifies_tool_timeout_in_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            transport = FakeTransport(
                [
                    ModelResponse(tool_calls=[ToolCall(id="tc1", name="bash", arguments={"command": "python -c 'import time; time.sleep(2)'"})]),
                ]
            )
            trace_store = InMemoryTraceStore()
            runtime = AgentRuntime(
                transport=transport,
                trace_store=trace_store,
                tool_registry=ToolRegistry(
                    registered_tools=[
                        ("terminal", BashTool(root=Path(tmpdir), default_timeout_seconds=1, max_timeout_seconds=1))
                    ]
                ),
                max_iterations=1,
            )

            result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(result.status, "iteration_limit_exceeded")
        self.assertEqual(trace_store.traces[0].tool_executions[0].error_category, "retryable")
        self.assertEqual(trace_store.traces[0].tool_executions[0].error_type, "TimeoutError")
        self.assertTrue(trace_store.traces[0].tool_executions[0].retryable)

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

    def test_runtime_falls_back_when_tool_renderer_returns_empty_text(self) -> None:
        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "ping"})]),
                ModelResponse(content="done"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            tool_result_renderer=EmptyToolResultRenderer(),
            tool_registry=ToolRegistry(
                tools={
                    "echo": lambda value: ToolResult.ok(
                        "echo",
                        "",
                        structured_content={"value": value},
                    )
                }
            ),
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="hello")

        self.assertEqual(result.messages[-2].content, "echo: success")

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
            trace_store=InMemoryTraceStore(),
            tool_registry=ToolRegistry(
                tools={"write_file": lambda path, content: ToolResult.ok("write_file", "written")},
                policy=DenyPolicy(),
            ),
        )

        result = runtime.run_conversation(session_id="s1", user_id="u1", user_message="write file")

        self.assertEqual(result.tool_results[0].status, "error")
        self.assertIn("requires approval", result.messages[-2].content)
        trace = runtime._trace_store.traces[0]
        self.assertEqual(trace.error_count, 1)
        self.assertEqual(trace.approval_count, 0)
        self.assertFalse(trace.tool_executions[0].approval_required)

    def test_runtime_counts_approval_required_tool_results(self) -> None:
        class AskPolicy:
            def decide(self, tool_name: str, arguments: dict, context: ToolContext | None) -> ToolDecision:
                return ToolDecision.ask("write_file requires approval")

        transport = FakeTransport(
            [
                ModelResponse(tool_calls=[ToolCall(id="tc1", name="write_file", arguments={"path": "a.txt", "content": "x"})]),
                ModelResponse(content="done"),
            ]
        )
        runtime = AgentRuntime(
            transport=transport,
            trace_store=InMemoryTraceStore(),
            tool_registry=ToolRegistry(
                tools={"write_file": lambda path, content: ToolResult.ok("write_file", "written")},
                policy=AskPolicy(),
            ),
        )

        runtime.run_conversation(session_id="s1", user_id="u1", user_message="write file")

        trace = runtime._trace_store.traces[0]
        self.assertEqual(trace.approval_count, 1)
        self.assertTrue(trace.tool_executions[0].approval_required)


if __name__ == "__main__":
    unittest.main()
