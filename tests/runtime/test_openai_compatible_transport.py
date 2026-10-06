import types
import unittest
from copy import deepcopy

from navi_agent.runtime import Message, ModelRequest, OpenAICompatibleTransport, ToolCall
from navi_agent.runtime.agent.control import RunCancelledError


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
    def test_appending_runtime_context_preserves_prefix_in_both_modes(self) -> None:
        history = [
            Message(role="system", content="Stable instructions."),
            Message(role="user", content="Run the checks."),
            Message(
                role="assistant",
                content="",
                reasoning_content="Start the checks in the background.",
                tool_calls=[ToolCall(id="c1", name="bash", arguments={"background": True})],
            ),
            Message(role="tool", content="Running; task_id=t1", tool_call_id="c1"),
            Message(role="assistant", content="The checks are running."),
        ]
        for role in ("runtime", "system"):
            for streaming in (False, True):
                with self.subTest(role=role, streaming=streaming):
                    messages = list(history)
                    previous = self._generate_with_messages(
                        messages, streaming=streaming,
                    ).chat.completions.calls[0]["messages"]
                    for task_id in ("t1", "t2"):
                        content = f"[Background task completed]\ntask_id: {task_id}"
                        messages.append(Message(role=role, content=content))
                        original = deepcopy(messages)
                        current = self._generate_with_messages(
                            messages, streaming=streaming,
                        ).chat.completions.calls[0]["messages"]
                        self.assertEqual(current[:-1], previous)
                        self.assertEqual(current[-1], {
                            "role": "user", "content": f"[Runtime context]\n{content}",
                        })
                        self.assertEqual(messages, original)
                        self.assertEqual([m["role"] for m in current].count("system"), 1)
                        previous = current

    def test_legacy_system_context_stays_at_its_original_position(self) -> None:
        messages = [
            Message(role="system", content="Stable instructions."),
            Message(role="system", content="[Context Summary]\nEarlier work."),
            Message(role="user", content="Continue."),
            Message(role="system", content="The verified completion condition has been reached."),
        ]
        original = deepcopy(messages)
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                wire = self._generate_with_messages(
                    messages, streaming=streaming,
                ).chat.completions.calls[0]["messages"]
                self.assertEqual(wire[0], {"role": "system", "content": "Stable instructions."})
                self.assertEqual([message["role"] for message in wire], ["system", "user", "user", "user"])
                self.assertEqual(wire[1]["content"], "[Runtime context]\n[Context Summary]\nEarlier work.")
                self.assertEqual(wire[2]["content"], "Continue.")
                self.assertIn("verified completion", wire[3]["content"])
                self.assertEqual(messages, original)

    def test_serialization_handles_missing_empty_and_late_system_messages(self) -> None:
        user = Message(role="user", content="hello")
        cases = [
            ([], []),
            ([user], [{"role": "user", "content": "hello"}]),
            ([Message(role="system", content=""), user], [
                {"role": "system", "content": ""}, {"role": "user", "content": "hello"},
            ]),
            ([user, Message(role="system", content="notification")], [
                {"role": "user", "content": "hello"},
                {"role": "user", "content": "[Runtime context]\nnotification"},
            ]),
            ([Message(role="runtime", content="notification")], [
                {"role": "user", "content": "[Runtime context]\nnotification"},
            ]),
        ]
        for messages, expected in cases:
            for streaming in (False, True):
                with self.subTest(messages=messages, streaming=streaming):
                    wire = self._generate_with_messages(
                        messages, streaming=streaming,
                    ).chat.completions.calls[0]["messages"]
                    self.assertEqual(wire, expected)

    def test_serialization_drops_unanswered_tool_calls(self) -> None:
        messages = [
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="echo", arguments={"value": "one"}),
                    ToolCall(id="tc2", name="echo", arguments={"value": "two"}),
                ],
            ),
            Message(role="tool", content="one", tool_call_id="tc1"),
            Message(role="user", content="Continue."),
        ]

        client = self._generate_with_messages(messages, streaming=False)

        self.assertEqual(
            client.chat.completions.calls[0]["messages"],
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "tc1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": '{"value": "one"}',
                        },
                    }],
                },
                {"role": "tool", "content": "one", "tool_call_id": "tc1"},
                {"role": "user", "content": "Continue."},
            ],
        )

    def test_serialization_drops_all_tool_calls_when_no_result_arrives(self) -> None:
        messages = [
            Message(
                role="assistant",
                content="waiting",
                tool_calls=[ToolCall(id="tc1", name="echo", arguments={})],
            )
        ]

        client = self._generate_with_messages(messages, streaming=False)

        self.assertEqual(
            client.chat.completions.calls[0]["messages"],
            [{"role": "assistant", "content": "waiting"}],
        )

    def test_transport_drops_orphaned_tool_messages_before_request(self) -> None:
        messages = [
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="tc1", name="bash", arguments={"command": "pwd"})],
            ),
            Message(role="tool", content="first", tool_call_id="tc1"),
            Message(role="assistant", content="follow-up"),
            Message(role="tool", content="duplicate", tool_call_id="tc1"),
        ]
        client = self._generate_with_messages(messages, streaming=False)
        serialized = client.chat.completions.calls[0]["messages"]
        self.assertEqual([message["role"] for message in serialized], ["assistant", "tool", "assistant"])

    @staticmethod
    def _generate_with_messages(messages, *, streaming):
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content="done", tool_calls=[]),
        )])
        client = FakeClient([] if streaming else response)
        transport = OpenAICompatibleTransport(model="model", api_key="test", client=client)
        request = ModelRequest(messages=messages)
        if streaming:
            transport.generate_stream(request, lambda _delta: None)
        else:
            transport.generate(request)
        return client

    def test_stream_closes_when_request_is_cancelled(self) -> None:
        class CancellableStream:
            def __init__(self) -> None:
                self.closed = False
                self._chunks = iter([object(), object()])

            def __iter__(self):
                return self

            def __next__(self):
                return next(self._chunks)

            def close(self) -> None:
                self.closed = True

        cancelled = False
        stream = CancellableStream()
        transport = OpenAICompatibleTransport(
            model="model",
            api_key="test",
            client=FakeClient(stream),
        )

        def cancellation_requested() -> bool:
            nonlocal cancelled
            was_cancelled = cancelled
            cancelled = True
            return was_cancelled

        with self.assertRaises(RunCancelledError):
            transport.generate_stream(
                ModelRequest(
                    messages=[Message(role="user", content="hi")],
                    cancellation_requested=cancellation_requested,
                ),
                lambda _delta: None,
            )

        self.assertTrue(stream.closed)

    def test_transport_streams_text_and_aggregates_response(self) -> None:
        chunks = [
            types.SimpleNamespace(
                model="deepseek-v4-pro",
                usage=None,
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(
                            content="hello ",
                            reasoning_content="internal ",
                            tool_calls=None,
                        )
                    )
                ],
            ),
            types.SimpleNamespace(
                model="deepseek-v4-pro",
                usage=None,
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(
                            content="world",
                            reasoning_content="reasoning",
                            tool_calls=None,
                        )
                    )
                ],
            ),
            types.SimpleNamespace(
                model="deepseek-v4-pro",
                usage=types.SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=2,
                    prompt_tokens_details=None,
                    completion_tokens_details=None,
                ),
                choices=[],
            ),
        ]
        client = FakeClient(chunks)
        transport = OpenAICompatibleTransport(model="deepseek-v4-pro", api_key="test", client=client)
        deltas: list[str] = []

        result = transport.generate_stream(
            ModelRequest(messages=[Message(role="user", content="hi")]),
            deltas.append,
        )

        self.assertEqual(deltas, ["hello ", "world"])
        self.assertEqual(result.content, "hello world")
        self.assertEqual(result.reasoning_content, "internal reasoning")
        self.assertEqual(result.model, "deepseek-v4-pro")
        self.assertEqual(result.usage.input_tokens, 10)
        self.assertEqual(result.usage.output_tokens, 2)
        call = client.chat.completions.calls[0]
        self.assertTrue(call["stream"])
        self.assertEqual(call["stream_options"], {"include_usage": True})

    def test_transport_aggregates_streamed_tool_calls(self) -> None:
        chunks = [
            types.SimpleNamespace(
                model="model",
                usage=None,
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                types.SimpleNamespace(
                                    index=0,
                                    id="tc1",
                                    function=types.SimpleNamespace(name="echo", arguments='{"value":'),
                                )
                            ],
                        )
                    )
                ],
            ),
            types.SimpleNamespace(
                model="model",
                usage=None,
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                types.SimpleNamespace(
                                    index=0,
                                    id=None,
                                    function=types.SimpleNamespace(name=None, arguments='"ping"}'),
                                )
                            ],
                        )
                    )
                ],
            ),
        ]
        transport = OpenAICompatibleTransport(
            model="model",
            api_key="test",
            client=FakeClient(chunks),
        )

        result = transport.generate_stream(
            ModelRequest(messages=[Message(role="user", content="hi")]),
            lambda _delta: None,
        )

        self.assertEqual(
            result.tool_calls,
            [ToolCall(id="tc1", name="echo", arguments={"value": "ping"})],
        )

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
