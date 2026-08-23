"""Error normalization middleware.

Converts all errors to structured CallToolResult with error categories.
Implements error taxonomy from capability/error_taxonomy.py.
"""

from __future__ import annotations

from fastmcp.server.middleware.middleware import Middleware
from fastmcp.server.context import Context
from fastmcp.resources.base import TextContent
from mcp.types import CallToolResult
import traceback


class ErrorNormalizationMiddleware(Middleware):
    """Normalizes all errors to structured error responses.

    Every error (exception) is caught and converted to:
    - CallToolResult with isError=True
    - Structured error metadata (category, code, message)
    - Tenant context for audit
    """

    async def on_call_tool(self, context, call_next):
        """Catch tool errors and normalize."""
        try:
            return await call_next(context)
        except Exception as e:
            tenant = getattr(context, "tenant", None)
            return self._build_error_result(e, tenant, context.message.name)

    async def on_read_resource(self, context, call_next):
        """Catch resource errors and normalize."""
        try:
            return await call_next(context)
        except Exception as e:
            tenant = getattr(context, "tenant", None)
            return self._build_error_result(e, tenant, context.message.uri)

    def _build_error_result(self, error: Exception, tenant, identifier: str) -> CallToolResult:
        """Build structured error response."""

        # Categorize the error
        category = self._categorize_error(error)
        code = type(error).__name__
        message = str(error)

        # Build structured error metadata
        error_meta = {
            "category": category,
            "code": code,
            "message": message,
            "tenant_id": tenant.id if tenant else "unknown",
            "recoverable": self._is_recoverable(category),
        }

        # Include stack trace in debug mode
        if False:  # Enable for dev if needed
            error_meta["traceback"] = traceback.format_exc()

        return CallToolResult(
            content=[TextContent(text=f"Error [{category}]: {message}")],
            isError=True,
            meta=error_meta,
        )

    def _categorize_error(self, error: Exception) -> str:
        """Categorize error into standard taxonomy."""

        if isinstance(error, ValueError):
            return "VALIDATION_ERROR"
        elif isinstance(error, PermissionError):
            return "AUTH_ERROR"
        elif isinstance(error, KeyError):
            return "NOT_FOUND_ERROR"
        elif isinstance(error, RuntimeError):
            return "PROVIDER_ERROR"
        elif isinstance(error, TimeoutError):
            return "TRANSIENT_ERROR"
        else:
            return "PROVIDER_ERROR"

    def _is_recoverable(self, category: str) -> bool:
        """Determine if error is transient/recoverable."""
        return category in {"TRANSIENT_ERROR", "PROVIDER_ERROR"}
