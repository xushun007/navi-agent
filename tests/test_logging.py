import logging
import tempfile
import unittest
from pathlib import Path

from navi_agent.logging import set_console_log_level, setup_logging


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

    def test_set_console_log_level_preserves_file_logging(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "navi-agent.log"
            logger = setup_logging(level="INFO", log_path=log_path)

            set_console_log_level("WARNING")
            logger.info("file only")

            stream_handler = next(
                handler
                for handler in logger.handlers
                if isinstance(handler, logging.StreamHandler)
                and not isinstance(handler, logging.FileHandler)
            )
            file_handler = next(
                handler for handler in logger.handlers if isinstance(handler, logging.FileHandler)
            )
            self.assertEqual(stream_handler.level, logging.WARNING)
            self.assertEqual(file_handler.level, logging.NOTSET)
            self.assertIn("file only", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
