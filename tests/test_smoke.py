from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navi_agent.doctor import DoctorReport
from navi_agent.smoke import SmokeRunStore, SmokeWorkflowService


class SmokeWorkflowTests(unittest.TestCase):
    def test_smoke_workflow_runs_core_checks_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir) / "smoke-reports"
            service = SmokeWorkflowService(report_root=report_root)

            with patch("navi_agent.smoke.collect_report", return_value=DoctorReport(ok=True, lines=["transport: ok"])):
                summary = service.run()
                latest = SmokeRunStore(report_root).get_latest()

        self.assertEqual(summary.count, 5)
        self.assertEqual(summary.passed_count, 5)
        self.assertEqual(summary.failed_count, 0)
        self.assertEqual(summary.pass_rate, 1.0)
        self.assertIsNotNone(summary.report_path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["count"], 5)
        self.assertEqual(latest["passed_count"], 5)
        tool_use = next(result for result in summary.results if result.name == "tool_use_regression")
        self.assertEqual(tool_use.metadata["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()
