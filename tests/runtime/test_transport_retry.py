from __future__ import annotations

import httpx
import unittest
from unittest.mock import patch

from openai import APITimeoutError, APIConnectionError, BadRequestError, InternalServerError, RateLimitError

from navi_agent.runtime.transports.openai_compatible import (
    OpenAICompatibleTransport,
    _is_retryable_error,
)
from navi_agent.runtime.models import Message
from navi_agent.runtime.transports.base import ModelRequest


class _FakeResponse:
    def __init__(self, response) -> None:
        self._response = response

    @property
    def choices(self):
        return [type("Choice", (), {"message": type("Message", (), {"content": "ok", "tool_calls": []})()})()]


class _FakeCompletions:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _FakeResponse(outcome)


class _FakeClient:
    def __init__(self, outcomes):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(outcomes)})()


class TransportRetryTests(unittest.TestCase):
    def test_retryable_error_classifier_handles_rate_limit_and_timeout(self) -> None:
        response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
        self.assertTrue(_is_retryable_error(RateLimitError("rate limit", response=response, body=None)))
        self.assertTrue(_is_retryable_error(APITimeoutError(request=httpx.Request("POST", "https://example.test"))))
        self.assertTrue(_is_retryable_error(APIConnectionError(request=httpx.Request("POST", "https://example.test"))))
        response_5xx = httpx.Response(503, request=httpx.Request("POST", "https://example.test"))
        self.assertTrue(_is_retryable_error(InternalServerError("server error", response=response_5xx, body=None)))

    def test_generate_retries_retryable_error_then_succeeds(self) -> None:
        response_429 = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
        fake_client = _FakeClient(
            [
                RateLimitError("rate limit", response=response_429, body=None),
                object(),
            ]
        )
        transport = OpenAICompatibleTransport(
            model="test-model",
            api_key="test-key",
            client=fake_client,
            max_retries=2,
            base_backoff_seconds=0.0,
            max_backoff_seconds=0.0,
        )

        with patch("navi_agent.runtime.transports.openai_compatible.time.sleep") as sleep_mock, patch(
            "navi_agent.runtime.transports.openai_compatible.random.random",
            return_value=0.0,
        ):
            result = transport.generate(ModelRequest(messages=[Message(role="user", content="hi")]))

        self.assertEqual(result.content, "ok")
        self.assertEqual(fake_client.chat.completions.calls, 2)
        sleep_mock.assert_called_once()

    def test_generate_raises_non_retryable_error_immediately(self) -> None:
        response_400 = httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
        fake_client = _FakeClient([BadRequestError("bad request", response=response_400, body=None)])
        transport = OpenAICompatibleTransport(
            model="test-model",
            api_key="test-key",
            client=fake_client,
            max_retries=2,
            base_backoff_seconds=0.0,
            max_backoff_seconds=0.0,
        )

        with self.assertRaises(BadRequestError):
            transport.generate(ModelRequest(messages=[Message(role="user", content="hi")]))

        self.assertEqual(fake_client.chat.completions.calls, 1)

    def test_generate_does_not_swallow_keyboard_interrupt(self) -> None:
        fake_client = _FakeClient([KeyboardInterrupt()])
        transport = OpenAICompatibleTransport(
            model="test-model",
            api_key="test-key",
            client=fake_client,
            max_retries=2,
            base_backoff_seconds=0.0,
            max_backoff_seconds=0.0,
        )

        with self.assertRaises(KeyboardInterrupt):
            transport.generate(ModelRequest(messages=[Message(role="user", content="hi")]))

        self.assertEqual(fake_client.chat.completions.calls, 1)


if __name__ == "__main__":
    unittest.main()
