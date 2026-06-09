import os
import unittest
from unittest.mock import patch

from navi_agent.config import LangfuseSettings


class LangfuseSettingsTests(unittest.TestCase):
    def test_from_sources_reads_yaml_config(self) -> None:
        settings = LangfuseSettings.from_sources(
            {
                "telemetry": {
                    "langfuse": {
                        "enabled": True,
                        "public_key": "pk-config",
                        "secret_key": "sk-config",
                        "host": "https://cloud.langfuse.com",
                    }
                }
            }
        )

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.public_key, "pk-config")
        self.assertEqual(settings.secret_key, "sk-config")
        self.assertEqual(settings.host, "https://cloud.langfuse.com")

    def test_from_sources_allows_env_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NAVI_LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "pk-env",
                "LANGFUSE_SECRET_KEY": "sk-env",
                "LANGFUSE_HOST": "https://example.langfuse.local",
            },
            clear=True,
        ):
            settings = LangfuseSettings.from_sources(
                {
                    "telemetry": {
                        "langfuse": {
                            "enabled": False,
                            "public_key": "pk-config",
                            "secret_key": "sk-config",
                            "host": "https://cloud.langfuse.com",
                        }
                    }
                }
            )

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.public_key, "pk-env")
        self.assertEqual(settings.secret_key, "sk-env")
        self.assertEqual(settings.host, "https://example.langfuse.local")


if __name__ == "__main__":
    unittest.main()
