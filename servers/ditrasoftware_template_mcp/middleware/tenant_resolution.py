"""Tenant resolution middleware template.

Customize to load tenant context from your auth system.
"""

from __future__ import annotations

from dataclasses import dataclass
from fastmcp.server.middleware.middleware import Middleware
from fastmcp.server.context import Context


@dataclass
class TenantContext:
    """Tenant scope resolved from request context."""

    id: str
    name: str
    tier: str  # "free" | "standard" | "enterprise"
    roles: list[str]
    scopes: list[str]
    region: str | None = None
    custom_config: dict = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def is_enterprise(self) -> bool:
        return self.tier == "enterprise"


class TenantResolutionMiddleware(Middleware):
    """Resolves tenant context from request.
    
    TODO: Customize _load_tenant() to fetch from your auth/database.
    """

    async def on_list_tools(self, context, call_next):
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def on_call_tool(self, context, call_next):
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def on_read_resource(self, context, call_next):
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def on_call_prompt(self, context, call_next):
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def _resolve_tenant(self, context: Context) -> TenantContext:
        """Extract tenant from request. Customize this."""
        
        # Priority 1: X-Tenant-Id header
        if context.request_context and context.request_context.request:
            tenant_id = context.request_context.request.headers.get("x-tenant-id")
            if tenant_id:
                return await self._load_tenant(tenant_id.strip())

        # Priority 2: Default tenant
        return await self._load_tenant("default")

    async def _load_tenant(self, tenant_id: str) -> TenantContext:
        """Load tenant from your auth system. Customize this."""
        
        # TODO: Replace with real tenant lookup (database, service, etc.)
        TENANT_STORE = {
            "default": TenantContext(
                id="default",
                name="Default Tenant",
                tier="enterprise",
                roles=["admin"],
                scopes=["*:read", "*:write"],
            ),
        }

        return TENANT_STORE.get(
            tenant_id,
            TenantContext(
                id="unknown",
                name="Unknown",
                tier="free",
                roles=[],
                scopes=["public:read"],
            ),
        )
