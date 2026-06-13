import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navi_agent.doctor import collect_report, run_doctor


class DoctorTests(unittest.TestCase):
    def test_collect_report_is_ok_when_model_config_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
model:
  name: gpt-4o-mini
  api_key: test-key
  base_url: https://example.com/v1

runtime:
  max_iterations: 5
""".strip(),
                encoding="utf-8",
            )

            with patch("navi_agent.doctor.is_langfuse_sdk_available", return_value=False):
                with patch.dict(os.environ, {"NAVI_HOME": tmpdir}, clear=True):
                    report = collect_report()

        self.assertTrue(report.ok)
        self.assertIn("config_exists: yes", report.lines)
        self.assertIn("api_key_configured: yes", report.lines)
        self.assertIn("langfuse_sdk_installed: no", report.lines)
        self.assertIn("transport: ok", report.lines)

    def test_collect_report_is_not_ok_when_api_key_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("navi_agent.doctor.is_langfuse_sdk_available", return_value=False):
                with patch.dict(os.environ, {"NAVI_HOME": tmpdir}, clear=True):
                    report = collect_report()

        self.assertFalse(report.ok)
        self.assertIn("config_exists: no", report.lines)
        self.assertIn("api_key_configured: no", report.lines)
        self.assertTrue(any(line.startswith("transport: error:") for line in report.lines))

    def test_collect_report_marks_langfuse_as_invalid_when_keys_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
model:
  name: gpt-4o-mini
  api_key: test-key

telemetry:
  langfuse:
    enabled: true
""".strip(),
                encoding="utf-8",
            )

            with patch("navi_agent.doctor.is_langfuse_sdk_available", return_value=False):
                with patch.dict(os.environ, {"NAVI_HOME": tmpdir}, clear=True):
                    report = collect_report()

        self.assertFalse(report.ok)
        self.assertIn("langfuse_enabled: yes", report.lines)
        self.assertIn("langfuse_keys_configured: no", report.lines)
        self.assertTrue(any(line.startswith("langfuse_exporter: error:") for line in report.lines))

    def test_collect_report_marks_langfuse_exporter_ok_when_sdk_and_keys_are_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
model:
  name: gpt-4o-mini
  api_key: test-key

telemetry:
  langfuse:
    enabled: true
    public_key: pk
    secret_key: sk
    host: https://cloud.langfuse.com
""".strip(),
                encoding="utf-8",
            )

            with patch("navi_agent.doctor.is_langfuse_sdk_available", return_value=True):
                with patch("navi_agent.doctor.LangfuseTraceExporter.from_settings", return_value=object()):
                    with patch.dict(os.environ, {"NAVI_HOME": tmpdir}, clear=True):
                        report = collect_report()

        self.assertTrue(report.ok)
        self.assertIn("langfuse_sdk_installed: yes", report.lines)
        self.assertIn("langfuse_keys_configured: yes", report.lines)
        self.assertIn("langfuse_exporter: ok", report.lines)

    def test_run_doctor_returns_non_zero_when_report_is_not_ok(self) -> None:
        output: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("navi_agent.doctor.is_langfuse_sdk_available", return_value=False):
                with patch.dict(os.environ, {"NAVI_HOME": tmpdir}, clear=True):
                    exit_code = run_doctor(output_fn=output.append)

        self.assertEqual(exit_code, 1)
        self.assertTrue(output)


if __name__ == "__main__":
    unittest.main()
