import types
import unittest

from navi_agent.runtime import Message, ModelRequest, OpenAICompatibleTransport, ToolCall


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.chat = types.SimpleNamespace(
            completions=FakeCompletions(response)
        )


class OpenAICompatibleTransportTests(unittest.TestCase):
    def test_transport_serializes_messages_and_tools(self) -> None:
        response = types.SimpleNamespace(
            model="gpt-4o-mini-2026-07-01",
            usage=types.SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=30,
                prompt_tokens_details=types.SimpleNamespace(cached_tokens=40),
                completion_tokens_details=types.SimpleNamespace(reasoning_tokens=10),
                cost=0.0025,
            ),
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content="done",
                        tool_calls=[],
                    )
                )
            ]
        )
        client = FakeClient(response)
        transport = OpenAICompatibleTransport(
            model="gpt-4o-mini",
            api_key="test",
            client=client,
        )

        request = ModelRequest(
            messages=[
                Message(role="system", content="system"),
                Message(role="user", content="hello"),
            ],
            tools=[
                {
                    "name": "echo",
                    "description": "Echo input",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                }
            ],
        )

        result = transport.generate(request)

        self.assertEqual(result.content, "done")
        self.assertEqual(result.provider, "openai-compatible")
        self.assertEqual(result.model, "gpt-4o-mini-2026-07-01")
        self.assertEqual(result.usage.input_tokens, 120)
        self.assertEqual(result.usage.output_tokens, 30)
        self.assertEqual(result.usage.cache_read_tokens, 40)
        self.assertEqual(result.usage.reasoning_tokens, 10)
        self.assertEqual(result.usage.cost_usd, 0.0025)
        call = client.chat.completions.calls[0]
        self.assertEqual(call["model"], "gpt-4o-mini")
        self.assertEqual(call["messages"][0]["role"], "system")
        self.assertEqual(call["messages"][1]["content"], "hello")
        self.assertEqual(call["tools"][0]["function"]["name"], "echo")
        self.assertEqual(
            call["tools"][0]["function"]["parameters"],
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )

    def test_transport_serializes_reasoning_content(self) -> None:
        response = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content="done",
                        tool_calls=[],
                    )
                )
            ]
        )
        client = FakeClient(response)
        transport = OpenAICompatibleTransport(
            model="gpt-4o-mini",
            api_key="test",
            client=client,
        )

        transport.generate(
            ModelRequest(
                messages=[
                    Message(
                        role="assistant",
                        content="working",
                        reasoning_content="internal trace",
                    )
                ]
            )
        )

        call = client.chat.completions.calls[0]
        self.assertEqual(call["messages"][0]["reasoning_content"], "internal trace")

    def test_transport_parses_tool_calls_from_response(self) -> None:
        response = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content=None,
                        tool_calls=[
                            types.SimpleNamespace(
                                id="tc1",
                                function=types.SimpleNamespace(
                                    name="echo",
                                    arguments='{"value":"ping"}',
                                ),
                            )
                        ],
                    )
                )
            ]
        )
        client = FakeClient(response)
        transport = OpenAICompatibleTransport(
            model="gpt-4o-mini",
            api_key="test",
            client=client,
        )

        result = transport.generate(ModelRequest(messages=[Message(role="user", content="hi")]))

        self.assertEqual(result.content, "")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0], ToolCall(id="tc1", name="echo", arguments={"value": "ping"}))

    def test_transport_parses_reasoning_content_from_response(self) -> None:
        response = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content="done",
                        reasoning_content="internal trace",
                        tool_calls=[],
                    )
                )
            ]
        )
        client = FakeClient(response)
        transport = OpenAICompatibleTransport(
            model="gpt-4o-mini",
            api_key="test",
            client=client,
        )

        result = transport.generate(ModelRequest(messages=[Message(role="user", content="hi")]))

        self.assertEqual(result.reasoning_content, "internal trace")


if __name__ == "__main__":
    unittest.main()
