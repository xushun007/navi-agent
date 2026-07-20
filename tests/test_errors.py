from __future__ import annotations

import unittest

from navi_agent.errors import classify_exception, is_retryable_exception, retry_delay


class _HTTPError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _StatusError(RuntimeError):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class ErrorClassificationTests(unittest.TestCase):
    def test_classifies_retryable_http_statuses(self) -> None:
        for status in [429, 500, 502, 503, 504]:
            with self.subTest(status=status):
                error = classify_exception(_HTTPError(status), error_source="model")

                self.assertEqual(error.error_category, "retryable")
                self.assertTrue(error.retryable)
                self.assertEqual(error.http_status, status)
                self.assertEqual(error.error_source, "model")

    def test_classifies_non_retryable_http_status(self) -> None:
        error = classify_exception(_StatusError(400), error_source="gateway")

        self.assertEqual(error.error_category, "fatal")
        self.assertFalse(error.retryable)
        self.assertEqual(error.http_status, 400)
        self.assertEqual(error.error_source, "gateway")

    def test_classifies_timeout_and_connection_text_as_retryable(self) -> None:
        self.assertTrue(is_retryable_exception(TimeoutError("timed out")))
        self.assertTrue(is_retryable_exception(RuntimeError("connection reset by peer")))

    def test_retry_delay_uses_bounded_exponential_backoff(self) -> None:
        self.assertEqual(
            retry_delay(attempt=4, base_seconds=0.5, max_seconds=2.0, jitter_ratio=0.0),
            2.0,
        )


if __name__ == "__main__":
    unittest.main()
