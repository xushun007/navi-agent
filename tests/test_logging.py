import logging
import tempfile
import unittest
from pathlib import Path

from navi_agent.logging import setup_logging


class LoggingTests(unittest.TestCase):
    def test_setup_logging_creates_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "logs" / "navi-agent.log"
            logger = setup_logging(level="DEBUG", log_path=log_path)

            logger.info("hello")

            self.assertTrue(log_path.exists())
            self.assertIn("hello", log_path.read_text(encoding="utf-8"))

    def test_setup_logging_sets_logger_level(self) -> None:
        logger = setup_logging(level="WARNING")

        self.assertEqual(logger.level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
