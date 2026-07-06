import os
import unittest
from pathlib import Path
from unittest.mock import patch

from navi_agent.paths import (
    get_app_log_path,
    get_candidate_store_path,
    get_config_path,
    get_evolution_dir,
    get_evolution_reports_dir,
    get_logs_dir,
    get_navi_home,
    get_prompt_overlay_path,
    get_prompt_overlay_snapshots_dir,
    get_smoke_reports_dir,
    get_state_db_path,
    get_eval_case_store_path,
)


class PathsTests(unittest.TestCase):
    def test_get_navi_home_uses_env_override(self) -> None:
        with patch.dict(os.environ, {"NAVI_HOME": "/tmp/navi-home"}, clear=True):
            self.assertEqual(get_navi_home(), Path("/tmp/navi-home"))

    def test_get_state_db_path_defaults_under_home(self) -> None:
        with patch.dict(os.environ, {"NAVI_HOME": "/tmp/navi-home"}, clear=True):
            self.assertEqual(get_state_db_path(), Path("/tmp/navi-home/state.db"))

    def test_get_logs_dir_and_log_path_use_navi_home(self) -> None:
        with patch.dict(os.environ, {"NAVI_HOME": "/tmp/navi-home"}, clear=True):
            self.assertEqual(get_logs_dir(), Path("/tmp/navi-home/logs"))
            self.assertEqual(get_app_log_path(), Path("/tmp/navi-home/logs/navi-agent.log"))
            self.assertEqual(get_config_path(), Path("/tmp/navi-home/config.yaml"))
            self.assertEqual(get_evolution_dir(), Path("/tmp/navi-home/evolution"))
            self.assertEqual(get_evolution_reports_dir(), Path("/tmp/navi-home/logs/evolution"))
            self.assertEqual(get_prompt_overlay_path(), Path("/tmp/navi-home/evolution/prompt-overlay.md"))
            self.assertEqual(get_prompt_overlay_snapshots_dir(), Path("/tmp/navi-home/evolution/prompt-overlay-snapshots"))
            self.assertEqual(get_candidate_store_path(), Path("/tmp/navi-home/evolution/candidates.jsonl"))
            self.assertEqual(get_smoke_reports_dir(), Path("/tmp/navi-home/smoke-reports"))
            self.assertEqual(
                get_eval_case_store_path(),
                Path("/tmp/navi-home/evolution/eval-cases.jsonl"),
            )

    def test_get_navi_home_defaults_under_workspace_when_env_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("navi_agent.paths.Path.cwd", return_value=Path("/tmp/workspace")):
                self.assertEqual(get_navi_home(), Path("/tmp/workspace/.navi-agent"))


if __name__ == "__main__":
    unittest.main()
