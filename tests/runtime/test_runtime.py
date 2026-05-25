import unittest

from navi_agent.runtime import (
    AgentRuntime,
    InMemorySessionStore,
    ModelRequest,
    ModelResponse,
    PromptBuilder,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
)


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, request: ModelRequest):
        self.calls.append(request)
        return self._responses.pop(0)


class TrackingPromptBuilder(PromptBuilder):
    def __init__(self) -> None:
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
            tool_registry=ToolRegistry(tools={"echo": lambda value: f"tool:{value}"}),
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
                        handler=lambda value: value,
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


if __name__ == "__main__":
    unittest.main()
