"""Guards the one rule that decides whether a failed run pages the owner.

Run: python3 tools/test_scraper_autofix_bot.py
"""
from __future__ import annotations

import importlib.util
import io
import unittest
import urllib.error
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "scraper_autofix_bot", Path(__file__).resolve().parent / "scraper_autofix_bot.py"
)
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


def http_error(code: str | int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.deepseek.com/v1/chat/completions", code, "err", {}, io.BytesIO(body)
    )


class ProviderErrorClassificationTest(unittest.TestCase):
    def test_an_empty_balance_does_not_fail_the_run(self):
        # The real payload that took the scheduled workflow red every 30 minutes.
        exc = bot._provider_error(
            http_error(402, b'{"error":{"message":"Insufficient Balance"}}'), "DeepSeek API"
        )
        self.assertIsInstance(exc, bot.ProviderUnavailable)
        self.assertIn("Insufficient Balance", str(exc))

    def test_auth_quota_and_outage_statuses_are_retry_later(self):
        for code in (401, 402, 403, 408, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                self.assertIsInstance(
                    bot._provider_error(http_error(code), "DeepSeek API"),
                    bot.ProviderUnavailable,
                )

    def test_a_network_failure_with_no_status_is_retry_later(self):
        self.assertIsInstance(
            bot._provider_error(urllib.error.URLError("connection refused"), "DeepSeek API"),
            bot.ProviderUnavailable,
        )

    def test_a_malformed_request_still_fails_loudly(self):
        # A dead model name arrives as 400/404. That is our bug, and silently
        # exiting 0 on it would hide a genuinely broken bot indefinitely.
        for code in (400, 404, 422):
            with self.subTest(code=code):
                exc = bot._provider_error(http_error(code), "DeepSeek API")
                self.assertIsInstance(exc, SystemExit)
                self.assertNotIsInstance(exc, bot.ProviderUnavailable)

    def test_provider_unavailable_is_catchable_as_an_exception(self):
        # SystemExit is not an Exception, which is why the old code escaped the
        # bot's own per-issue handler and killed the whole run.
        self.assertTrue(issubclass(bot.ProviderUnavailable, Exception))


if __name__ == "__main__":
    unittest.main()
