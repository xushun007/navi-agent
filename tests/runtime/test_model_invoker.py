import unittest

from navi_agent.runtime.agent.model_invoker import ModelInvoker
from navi_agent.runtime.models import Message, ModelResponse


class RecordingTransport:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return self.response


class StreamingTransport(RecordingTransport):
    def generate(self, request):
        raise AssertionError("generate must not be called")

    def generate_stream(self, request, on_text_delta):
        self.requests.append(request)
        on_text_delta("one")
        on_text_delta("two")
        return self.response


class ModelInvokerTest(unittest.TestCase):
    def test_invokes_transport_with_runtime_request_data(self) -> None:
        response = ModelResponse(content="done")
        transport = RecordingTransport(response)
        cancelled = lambda: False

        invocation = ModelInvoker(transport).invoke(
            messages=[Message(role="user", content="hello")],
            tools=[{"type": "function"}],
            cancellation_requested=cancelled,
            on_text_delta=lambda _delta: None,
        )

        self.assertIs(invocation.response, response)
        self.assertEqual(transport.requests[0].messages[0].content, "hello")
        self.assertEqual(transport.requests[0].tools, [{"type": "function"}])
        self.assertIs(transport.requests[0].cancellation_requested, cancelled)
        self.assertTrue(invocation.started_at)
        self.assertTrue(invocation.completed_at)
        self.assertGreaterEqual(invocation.duration_ms, 0)

    def test_prefers_streaming_transport_and_forwards_deltas(self) -> None:
        transport = StreamingTransport(ModelResponse(content="onetwo"))
        deltas = []

        invocation = ModelInvoker(transport).invoke(
            messages=[],
            tools=[],
            cancellation_requested=lambda: False,
            on_text_delta=deltas.append,
        )

        self.assertEqual(invocation.response.content, "onetwo")
        self.assertEqual(deltas, ["one", "two"])


if __name__ == "__main__":
    unittest.main()
