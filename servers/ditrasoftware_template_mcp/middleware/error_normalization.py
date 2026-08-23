"""Error normalization middleware template."""

from fastmcp.server.middleware.middleware import Middleware
from fastmcp.resources.base import TextContent
from mcp.types import CallToolResult


class ErrorNormalizationMiddleware(Middleware):
    """Converts all errors to structured CallToolResult.
    
    TODO: Customize _categorize_error() for your domain.
    """

    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except Exception as e:
            tenant = getattr(context, "tenant", None)
            return self._build_error_result(e, tenant)

    async def on_read_resource(self, context, call_next):
        try:
            return await call_next(context)
        except Exception as e:
            tenant = getattr(context, "tenant", None)
            return self._build_error_result(e, tenant)

    def _build_error_result(self, error: Exception, tenant) -> CallToolResult:
        """Build structured error response."""
        
        category = self._categorize_error(error)
        
        return CallToolResult(
            content=[TextContent(text=f"Error [{category}]: {str(error)}")],
            isError=True,
            meta={
                "category": category,
                "code": type(error).__name__,
                "message": str(error),
                "tenant_id": tenant.id if tenant else "unknown",
            },
        )

    def _categorize_error(self, error: Exception) -> str:
        """Categorize error. TODO: Customize for your domain."""
        
        if isinstance(error, ValueError):
            return "VALIDATION_ERROR"
        elif isinstance(error, PermissionError):
            return "AUTH_ERROR"
        elif isinstance(error, KeyError):
            return "NOT_FOUND_ERROR"
        else:
            return "PROVIDER_ERROR"
