import os
import unittest
from unittest.mock import patch

from navi_agent.bootstrap import build_runtime
from navi_agent.config import ModelSettings, RuntimeSettings


class BootstrapTests(unittest.TestCase):
    def test_build_runtime_wires_transport_session_store_and_iterations(self) -> None:
        model_settings = ModelSettings(
            model="gpt-4o-mini",
            api_key="test-key",
            base_url="https://example.com/v1",
        )
        runtime_settings = RuntimeSettings(max_iterations=12)

        with patch("navi_agent.bootstrap.build_transport") as build_transport_mock:
            with patch("navi_agent.bootstrap.SQLiteSessionStore") as store_cls:
                with patch("navi_agent.bootstrap.setup_logging") as setup_logging_mock:
                    with patch("navi_agent.bootstrap.build_default_tool_registry") as build_registry_mock:
                        runtime = build_runtime(model_settings, runtime_settings)

        build_transport_mock.assert_called_once_with(model_settings)
        store_cls.assert_called_once()
        setup_logging_mock.assert_called_once()
        build_registry_mock.assert_called_once()
        self.assertEqual(runtime._max_iterations, 12)

    def test_build_runtime_reads_defaults_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NAVI_MODEL": "gpt-4o-mini",
                "NAVI_API_KEY": "test-key",
                "NAVI_HOME": "/tmp/navi-home",
            },
            clear=True,
        ):
            with patch("navi_agent.bootstrap.build_transport") as build_transport_mock:
                with patch("navi_agent.bootstrap.SQLiteSessionStore") as store_cls:
                    with patch("navi_agent.bootstrap.setup_logging") as setup_logging_mock:
                        with patch("navi_agent.bootstrap.build_default_tool_registry") as build_registry_mock:
                            build_runtime()

        build_transport_mock.assert_called_once()
        store_cls.assert_called_once()
        setup_logging_mock.assert_called_once()
        build_registry_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
