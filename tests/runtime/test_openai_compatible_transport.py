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


if __name__ == "__main__":
    unittest.main()
