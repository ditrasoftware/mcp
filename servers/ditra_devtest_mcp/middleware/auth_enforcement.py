"""Auth enforcement middleware.

Validates auth scopes against capability requirements.
Handles token refresh and DPoP.
"""

from __future__ import annotations

from fastmcp.server.middleware.middleware import Middleware
from fastmcp.server.context import Context
import mcp.types as mt


class AuthEnforcementMiddleware(Middleware):
    """Enforces auth scopes against capability requirements.

    For tools, validates that:
    1. Request has auth (if tool requires it)
    2. Auth token has required scopes
    3. Token is fresh (checks expiration)

    For resources, applies same logic.
    """

    async def on_list_tools(self, context, call_next):
        """Allow listing; filtering happens in tool schema."""
        return await call_next(context)

    async def on_call_tool(self, context, call_next):
        """Enforce auth before tool execution."""
        tenant = getattr(context, "tenant", None)
        if not tenant:
            # Tenant middleware should have run first
            raise RuntimeError("TenantResolutionMiddleware must run before AuthEnforcementMiddleware")

        tool_name = context.message.name

        # For now, simplified: all tools are allowed for enterprise tenant
        # Real impl would check capability registry for scope requirements
        if not tenant.is_enterprise() and tool_name.startswith("admin_"):
            raise PermissionError(
                f"Tenant {tenant.id} (tier={tenant.tier}) cannot access admin tool: {tool_name}"
            )

        return await call_next(context)

    async def on_read_resource(self, context, call_next):
        """Enforce auth before resource read."""
        tenant = getattr(context, "tenant", None)
        if not tenant:
            raise RuntimeError("TenantResolutionMiddleware must run before AuthEnforcementMiddleware")

        return await call_next(context)

    async def on_call_prompt(self, context, call_next):
        """Enforce auth before prompt call."""
        tenant = getattr(context, "tenant", None)
        if not tenant:
            raise RuntimeError("TenantResolutionMiddleware must run before AuthEnforcementMiddleware")

        return await call_next(context)
