import unittest
from unittest.mock import patch

from navi_agent.app import ApplicationService
from navi_agent.app.bootstrap import build_application


class BuildApplicationTests(unittest.TestCase):
    def test_build_application_wraps_runtime(self) -> None:
        fake_runtime = object()
        with patch("navi_agent.app.bootstrap.build_runtime", return_value=fake_runtime) as build_runtime_mock:
            app = build_application(default_system_prompt="system")

        self.assertIsInstance(app, ApplicationService)
        build_runtime_mock.assert_called_once()
        self.assertIs(app._runtime, fake_runtime)
        self.assertEqual(app._default_system_prompt, "system")

    def test_build_application_passes_approval_provider_to_runtime_builder(self) -> None:
        fake_runtime = object()
        provider = object()
        with patch("navi_agent.app.bootstrap.build_runtime", return_value=fake_runtime) as build_runtime_mock:
            build_application(default_system_prompt="system", approval_provider=provider)

        build_runtime_mock.assert_called_once()
        _, kwargs = build_runtime_mock.call_args
        self.assertEqual(kwargs["model_settings"], None)
        self.assertEqual(kwargs["runtime_settings"], None)
        self.assertIs(kwargs["approval_provider"], provider)
        self.assertIsNotNone(kwargs["skill_store"])


if __name__ == "__main__":
    unittest.main()
