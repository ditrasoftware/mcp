"""Auth enforcement middleware template."""

from fastmcp.server.middleware.middleware import Middleware
from fastmcp.server.context import Context


class AuthEnforcementMiddleware(Middleware):
    """Validates auth scopes against capability requirements.
    
    TODO: Customize to check your capability registry against tenant scopes.
    """

    async def on_call_tool(self, context, call_next):
        tenant = getattr(context, "tenant", None)
        if not tenant:
            raise RuntimeError("TenantResolutionMiddleware must run first")
        
        # TODO: Check tenant.scopes against tool requirements
        return await call_next(context)

    async def on_read_resource(self, context, call_next):
        tenant = getattr(context, "tenant", None)
        if not tenant:
            raise RuntimeError("TenantResolutionMiddleware must run first")
        
        return await call_next(context)

    async def on_call_prompt(self, context, call_next):
        tenant = getattr(context, "tenant", None)
        if not tenant:
            raise RuntimeError("TenantResolutionMiddleware must run first")
        
        return await call_next(context)
