import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navi_agent.config import ModelSettings, RuntimeSettings, WeixinGatewaySettings, load_config


class SettingsTests(unittest.TestCase):
    def test_model_settings_reads_navi_env_first(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NAVI_MODEL": "gpt-4.1-mini",
                "NAVI_API_KEY": "navi-key",
                "NAVI_BASE_URL": "https://example.com/v1",
                "NAVI_CONTEXT_LIMIT_TOKENS": "128000",
                "OPENAI_API_KEY": "openai-key",
            },
            clear=False,
        ):
            settings = ModelSettings.from_env()

        self.assertEqual(settings.model, "gpt-4.1-mini")
        self.assertEqual(settings.api_key, "navi-key")
        self.assertEqual(settings.base_url, "https://example.com/v1")
        self.assertEqual(settings.context_limit_tokens, 128000)

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
        self.assertEqual(settings.context_limit_tokens, 128000)

    def test_load_config_reads_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
model:
  name: gpt-4.1-mini
  api_key: file-key
  base_url: https://example.com/v1

runtime:
  max_iterations: 12
""".strip(),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config["model"]["name"], "gpt-4.1-mini")
        self.assertEqual(config["runtime"]["max_iterations"], 12)

    def test_model_settings_reads_from_config_file_values(self) -> None:
        config = {
            "model": {
                "name": "gpt-4.1-mini",
                "api_key": "file-key",
                "base_url": "https://example.com/v1",
                "context_limit_tokens": 64000,
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            settings = ModelSettings.from_sources(config)

        self.assertEqual(settings.model, "gpt-4.1-mini")
        self.assertEqual(settings.api_key, "file-key")
        self.assertEqual(settings.base_url, "https://example.com/v1")
        self.assertEqual(settings.context_limit_tokens, 64000)

    def test_runtime_settings_reads_iteration_limit(self) -> None:
        with patch.dict(os.environ, {"NAVI_MAX_ITERATIONS": "12"}, clear=True):
            settings = RuntimeSettings.from_env()

        self.assertEqual(settings.max_iterations, 12)

    def test_runtime_settings_reads_from_config_file_values(self) -> None:
        config = {
            "runtime": {
                "max_iterations": 15,
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            settings = RuntimeSettings.from_sources(config)

        self.assertEqual(settings.max_iterations, 15)

    def test_weixin_gateway_settings_reads_from_config_file_values(self) -> None:
        config = {
            "gateway": {
                "weixin": {
                    "token": "file-token",
                }
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            settings = WeixinGatewaySettings.from_sources(config)

        self.assertEqual(settings.token, "file-token")

    def test_weixin_gateway_settings_reads_ilink_values(self) -> None:
        config = {
            "gateway": {
                "weixin": {
                    "token": "file-token",
                    "account_id": "account-1",
                    "base_url": "https://ilink.example",
                    "poll_interval_seconds": 2.5,
                    "dm_policy": "pairing",
                    "allowed_users": ["user-1", "user-2"],
                }
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            settings = WeixinGatewaySettings.from_sources(config)

        self.assertEqual(settings.account_id, "account-1")
        self.assertEqual(settings.base_url, "https://ilink.example")
        self.assertEqual(settings.poll_interval_seconds, 2.5)
        self.assertEqual(settings.dm_policy, "pairing")
        self.assertEqual(settings.allowed_users, ("user-1", "user-2"))

    def test_weixin_gateway_settings_reads_env_first(self) -> None:
        config = {
            "gateway": {
                "weixin": {
                    "token": "file-token",
                }
            }
        }

        with patch.dict(
            os.environ,
            {
                "NAVI_WEIXIN_TOKEN": "env-token",
                "NAVI_WEIXIN_ACCOUNT_ID": "env-account",
                "NAVI_WEIXIN_BASE_URL": "https://env-ilink.example",
                "NAVI_WEIXIN_POLL_INTERVAL_SECONDS": "3.5",
                "NAVI_WEIXIN_DM_POLICY": "allowlist",
                "NAVI_WEIXIN_ALLOWED_USERS": "user-a,user-b",
            },
            clear=True,
        ):
            settings = WeixinGatewaySettings.from_sources(config)

        self.assertEqual(settings.token, "env-token")
        self.assertEqual(settings.account_id, "env-account")
        self.assertEqual(settings.base_url, "https://env-ilink.example")
        self.assertEqual(settings.poll_interval_seconds, 3.5)
        self.assertEqual(settings.dm_policy, "allowlist")
        self.assertEqual(settings.allowed_users, ("user-a", "user-b"))
