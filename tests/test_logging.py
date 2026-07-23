import logging
from logging.handlers import RotatingFileHandler
import stat
import tempfile
import unittest
from pathlib import Path

from navi_agent.logging import redact_sensitive_data, set_console_log_level, setup_logging


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

    def test_setup_logging_rotates_and_protects_log_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "logs" / "navi-agent.log"
            logger = setup_logging(
                level="INFO",
                log_path=log_path,
                max_bytes=200,
                backup_count=2,
            )

            for index in range(20):
                logger.info("message-%s %s", index, "x" * 40)

            file_handler = next(
                handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)
            )
            self.assertEqual(file_handler.maxBytes, 200)
            self.assertEqual(file_handler.backupCount, 2)
            self.assertTrue(log_path.with_suffix(".log.1").exists())
            self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(log_path.parent.stat().st_mode), 0o700)

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

    def test_setup_logging_redacts_sensitive_values_and_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "navi-agent.log"
            logger = setup_logging(level="INFO", log_path=log_path)

            try:
                raise RuntimeError("authorization=Bearer private-token")
            except RuntimeError:
                logger.exception("request failed token=private-token")

            content = log_path.read_text(encoding="utf-8")
            self.assertNotIn("private-token", content)
            self.assertIn("token=<redacted>", content)
            self.assertIn("authorization=<redacted>", content)

    def test_redact_sensitive_data_handles_json_and_bearer_tokens(self) -> None:
        redacted = redact_sensitive_data(
            '{"api_key": "sk-private", "header": "Bearer bearer-private"}'
        )

        self.assertNotIn("sk-private", redacted)
        self.assertNotIn("bearer-private", redacted)
        self.assertIn("<redacted>", redacted)


if __name__ == "__main__":
    unittest.main()
