import os
import unittest
from pathlib import Path
from unittest.mock import patch

from navi_agent.paths import get_navi_home, get_state_db_path


class PathsTests(unittest.TestCase):
    def test_get_navi_home_uses_env_override(self) -> None:
        with patch.dict(os.environ, {"NAVI_HOME": "/tmp/navi-home"}, clear=True):
            self.assertEqual(get_navi_home(), Path("/tmp/navi-home"))

    def test_get_state_db_path_defaults_under_home(self) -> None:
        with patch.dict(os.environ, {"NAVI_HOME": "/tmp/navi-home"}, clear=True):
            self.assertEqual(get_state_db_path(), Path("/tmp/navi-home/state.db"))


if __name__ == "__main__":
    unittest.main()
