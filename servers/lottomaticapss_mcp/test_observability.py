from __future__ import annotations

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from .middleware.observability import (
    ObservabilityMiddleware, RedactAccessQueryFilter, access_log_config, logger,
)


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_results_are_logged_as_failed_without_logging_content(self):
        context = SimpleNamespace(message=SimpleNamespace(name="visualize_card"))
        for error_field in ("is_error", "isError"):
            result = SimpleNamespace(**{error_field: True}, content="sensitive-business-data", meta={})
            with self.assertLogs(logger, level="INFO") as captured:
                returned = await ObservabilityMiddleware().on_call_tool(context, AsyncMock(return_value=result))
            self.assertIs(returned, result)
            self.assertIn("visualize_card failed", captured.output[0])
            self.assertNotIn("sensitive-business-data", captured.output[0])

    async def test_native_preparation_is_not_logged_as_rendered(self):
        context = SimpleNamespace(message=SimpleNamespace(name="visualize_card"))
        result = SimpleNamespace(is_error=False, meta={"lottomaticapss/rendering": {"status": "prepared"}})
        with self.assertLogs(logger, level="INFO") as captured:
            await ObservabilityMiddleware().on_call_tool(context, AsyncMock(return_value=result))
        self.assertIn("visualize_card prepared", captured.output[0])

    async def test_unexpected_metadata_does_not_change_tool_results(self):
        context = SimpleNamespace(message=SimpleNamespace(name="visualize_card"))
        for value in (None, "sensitive-metadata", [], True, 42):
            for metadata in (value, {"lottomaticapss/rendering": value}):
                for failed in (False, True):
                    with self.subTest(metadata=metadata, failed=failed):
                        result = SimpleNamespace(is_error=failed, meta=metadata)
                        with self.assertLogs(logger, level="INFO") as captured:
                            returned = await ObservabilityMiddleware().on_call_tool(
                                context, AsyncMock(return_value=result))
                        self.assertIs(returned, result)
                        expected = "failed" if failed else "ok"
                        self.assertIn(f"visualize_card {expected}", captured.output[0])
                        self.assertNotIn("sensitive-metadata", captured.output[0])

    async def test_exception_is_logged_and_propagated(self):
        context = SimpleNamespace(message=SimpleNamespace(name="search"))
        with self.assertLogs(logger, level="INFO") as captured:
            with self.assertRaises(PermissionError):
                await ObservabilityMiddleware().on_call_tool(context, AsyncMock(side_effect=PermissionError("secret")))
        self.assertIn("search failed", captured.output[0])
        self.assertNotIn("secret", captured.output[0])

    def test_access_query_values_are_redacted_before_formatting(self):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1", "GET", "/connections/callback?code=secret-code&state=secret-state", "1.1", 200), None)
        self.assertTrue(RedactAccessQueryFilter().filter(record))
        self.assertIn("/connections/callback?[REDACTED]", record.getMessage())
        self.assertNotIn("secret-code", record.getMessage())
        self.assertNotIn("secret-state", record.getMessage())

    def test_redaction_is_attached_without_mutating_uvicorn_defaults(self):
        from uvicorn.config import LOGGING_CONFIG

        config = access_log_config()
        self.assertEqual(config["handlers"]["access"]["filters"], ["redact_query"])
        self.assertNotIn("redact_query", LOGGING_CONFIG.get("filters", {}))


if __name__ == "__main__":
    unittest.main()