import unittest
from unittest.mock import patch

from navi_agent.app import ApplicationService
from navi_agent.bootstrap import build_application


class BuildApplicationTests(unittest.TestCase):
    def test_build_application_wraps_runtime(self) -> None:
        fake_runtime = object()
        with patch("navi_agent.bootstrap.build_runtime", return_value=fake_runtime) as build_runtime_mock:
            app = build_application(default_system_prompt="system")

        self.assertIsInstance(app, ApplicationService)
        build_runtime_mock.assert_called_once()
        self.assertIs(app._runtime, fake_runtime)
        self.assertEqual(app._default_system_prompt, "system")

    def test_build_application_passes_demo_flag_to_runtime_builder(self) -> None:
        fake_runtime = object()
        with patch("navi_agent.bootstrap.build_runtime", return_value=fake_runtime) as build_runtime_mock:
            build_application(default_system_prompt="system", demo=True)

        build_runtime_mock.assert_called_once_with(
            model_settings=None,
            runtime_settings=None,
            demo=True,
        )


if __name__ == "__main__":
    unittest.main()
