import unittest
from unittest.mock import patch

from navi_agent.config import ModelSettings
from navi_agent.runtime.transport_factory import build_transport


class TransportFactoryTests(unittest.TestCase):
    def test_build_transport_creates_openai_compatible_transport(self) -> None:
        settings = ModelSettings(
            model="gpt-4o-mini",
            api_key="test-key",
            base_url="https://example.com/v1",
        )

        with patch("navi_agent.runtime.transport_factory.OpenAICompatibleTransport") as transport_cls:
            build_transport(settings)

        transport_cls.assert_called_once_with(
            model="gpt-4o-mini",
            api_key="test-key",
            base_url="https://example.com/v1",
        )

    def test_build_transport_requires_api_key(self) -> None:
        settings = ModelSettings(model="x", api_key=None)

        with self.assertRaisesRegex(ValueError, "Missing API key"):
            build_transport(settings)
