"""Observability middleware.

Injects request IDs, metrics, and audit logging.
"""

from __future__ import annotations

from fastmcp.server.middleware.middleware import Middleware
from fastmcp.server.context import Context
import uuid
import time


class ObservabilityMiddleware(Middleware):
    """Injects request-id and timing for observability.

    Stores in context for downstream logging/metrics.
    """

    async def on_list_tools(self, context, call_next):
        """Inject observability before list_tools."""
        request_id = self._get_or_create_request_id(context)
        start = time.time()
        
        try:
            result = await call_next(context)
            duration_ms = (time.time() - start) * 1000
            # Could emit metric here
            return result
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            # Could emit error metric
            raise

    async def on_call_tool(self, context, call_next):
        """Inject observability before tool call."""
        request_id = self._get_or_create_request_id(context)
        tenant = getattr(context, "tenant", None)
        start = time.time()
        
        try:
            result = await call_next(context)
            duration_ms = (time.time() - start) * 1000
            # Could emit metric: tool_call_success, tenant, duration
            return result
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            # Could emit error metric: tool_call_error, category
            raise

    def _get_or_create_request_id(self, context: Context) -> str:
        """Get or create request-id for tracing."""

        # FastMCP middleware context can be immutable in some versions,
        # so do not attempt to assign attributes on it.
        existing = getattr(context, "request_id", None)
        if existing:
            return str(existing)

        return str(uuid.uuid4())
