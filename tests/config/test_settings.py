import os
import unittest
from unittest.mock import patch

from navi_agent.config import ModelSettings, RuntimeSettings


class SettingsTests(unittest.TestCase):
    def test_model_settings_reads_navi_env_first(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NAVI_MODEL_PROVIDER": "openai_compatible",
                "NAVI_MODEL": "gpt-4.1-mini",
                "NAVI_API_KEY": "navi-key",
                "NAVI_BASE_URL": "https://example.com/v1",
                "OPENAI_API_KEY": "openai-key",
            },
            clear=False,
        ):
            settings = ModelSettings.from_env()

        self.assertEqual(settings.provider, "openai_compatible")
        self.assertEqual(settings.model, "gpt-4.1-mini")
        self.assertEqual(settings.api_key, "navi-key")
        self.assertEqual(settings.base_url, "https://example.com/v1")

    def test_model_settings_falls_back_to_openai_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_BASE_URL": "https://openai-compatible.test/v1",
            },
            clear=True,
        ):
            settings = ModelSettings.from_env()

        self.assertEqual(settings.model, "gpt-4o-mini")
        self.assertEqual(settings.api_key, "openai-key")
        self.assertEqual(settings.base_url, "https://openai-compatible.test/v1")

    def test_runtime_settings_reads_iteration_limit(self) -> None:
        with patch.dict(
            os.environ,
            {"NAVI_MAX_ITERATIONS": "12", "NAVI_LOG_LEVEL": "debug"},
            clear=True,
        ):
            settings = RuntimeSettings.from_env()

        self.assertEqual(settings.max_iterations, 12)
        self.assertEqual(settings.log_level, "DEBUG")
