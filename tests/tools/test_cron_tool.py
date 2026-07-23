from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from navi_agent.runtime import ToolContext
from navi_agent.runtime.tasks.cron import CronJobStore
from navi_agent.tools.cron_tool import CronTool


class CronToolTests(unittest.TestCase):
    def test_creates_lists_and_cancels_once_job(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tool = CronTool(CronJobStore(Path(tmpdir) / "jobs.json"))
            context = ToolContext(session_id="s1", user_id="u1", iteration=1)

            created = tool.invoke(
                context=context,
                action="once",
                prompt="check ci",
                run_at="2026-07-21T09:00:00+00:00",
            )
            listed = tool.invoke(context=context, action="list")
            cancelled = tool.invoke(context=context, action="cancel", id=created.structured_content["id"])

        self.assertEqual(created.status, "success")
        self.assertEqual(created.structured_content["schedule_type"], "once")
        self.assertIn("check ci", listed.structured_content["jobs"][0]["prompt"])
        self.assertEqual(cancelled.status, "success")
        self.assertFalse(cancelled.structured_content["enabled"])

    def test_rejects_invalid_cron_expression(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tool = CronTool(CronJobStore(Path(tmpdir) / "jobs.json"))
            result = tool.invoke(
                context=ToolContext(session_id="s1", user_id="u1", iteration=1),
                action="cron",
                prompt="poll ci",
                cron="bad",
            )

        self.assertEqual(result.status, "error")
        self.assertIn("cron expression", result.content)


if __name__ == "__main__":
    unittest.main()
