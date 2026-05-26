import unittest

from navi_agent.runtime import DemoTransport, Message, ModelRequest


class DemoTransportTests(unittest.TestCase):
    def test_returns_direct_text_reply_for_plain_prompt(self) -> None:
        transport = DemoTransport()

        result = transport.generate(
            ModelRequest(messages=[Message(role="user", content="hello")])
        )

        self.assertIn("demo", result.content.lower())
        self.assertEqual(result.tool_calls, [])
