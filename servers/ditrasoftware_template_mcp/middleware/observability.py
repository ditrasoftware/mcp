"""Observability middleware template."""

from fastmcp.server.middleware.middleware import Middleware
from fastmcp.server.context import Context
import uuid
import time


class ObservabilityMiddleware(Middleware):
    """Injects request-id and timing for observability.
    
    TODO: Add metrics emission (e.g., emit to StatsD, Prometheus).
    """

    async def on_call_tool(self, context, call_next):
        request_id = self._get_or_create_request_id(context)
        start = time.time()
        
        try:
            result = await call_next(context)
            duration_ms = (time.time() - start) * 1000
            # TODO: Emit metric: tool_call_success, duration, tool_name
            return result
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            # TODO: Emit metric: tool_call_error, duration, error_type
            raise

    def _get_or_create_request_id(self, context: Context) -> str:
        """Get or create request-id for tracing."""
        
        if hasattr(context, "request_id"):
            return context.request_id
        
        if context.request_context and context.request_context.request:
            req_id = context.request_context.request.headers.get("x-request-id")
            if req_id:
                context.request_id = req_id
                return req_id
        
        req_id = str(uuid.uuid4())
        context.request_id = req_id
        return req_id
