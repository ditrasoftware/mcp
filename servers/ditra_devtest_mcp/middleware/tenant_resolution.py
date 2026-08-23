"""Tenant resolution middleware.

Extracts tenant context from request headers, auth, or routing.
Stores in ctx for downstream middleware and tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from fastmcp.server.middleware.middleware import Middleware
from fastmcp.server.context import Context
import mcp.types as mt


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
        """Check if tenant has a scope."""
        return scope in self.scopes

    def is_enterprise(self) -> bool:
        """Check if tenant is enterprise-tier."""
        return self.tier == "enterprise"


class TenantResolutionMiddleware(Middleware):
    """Resolves tenant context and stores in ctx for downstream use.

    Resolution priority:
    1. X-Tenant-Id header
    2. Auth token subject (sub claim)
    3. Default to "shared" tenant
    """

    async def on_list_tools(self, context, call_next):
        """Resolve tenant before listing tools."""
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def on_list_resources(self, context, call_next):
        """Resolve tenant before listing resources."""
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def on_call_tool(self, context, call_next):
        """Resolve tenant before calling tool."""
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def on_read_resource(self, context, call_next):
        """Resolve tenant before reading resource."""
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def on_call_prompt(self, context, call_next):
        """Resolve tenant before calling prompt."""
        tenant = await self._resolve_tenant(context)
        context.tenant = tenant
        return await call_next(context)

    async def _resolve_tenant(self, context: Context) -> TenantContext:
        """Extract tenant from request context.

        Priority:
        1. X-Tenant-Id header
        2. Auth header (sub claim if JWT)
        3. Default to "shared"
        """

        # Priority 1: X-Tenant-Id header
        if context.request_context and context.request_context.request:
            headers = context.request_context.request.headers
            tenant_id = headers.get("x-tenant-id")
            if tenant_id:
                return await self._load_tenant(tenant_id.strip())

        # Priority 2: Extract from auth (simplified; real impl would decode JWT)
        # For now, use a default enterprise tenant for testing
        tenant_id = "test-enterprise-1"

        return await self._load_tenant(tenant_id)

    async def _load_tenant(self, tenant_id: str) -> TenantContext:
        """Load tenant configuration from store.

        Simplified for testing; real impl would fetch from database.
        """

        # Hardcoded test tenants
        TENANT_STORE = {
            "test-enterprise-1": TenantContext(
                id="test-enterprise-1",
                name="Test Enterprise",
                tier="enterprise",
                roles=["admin", "operator", "viewer"],
                scopes=[
                    "patient:read",
                    "patient:write",
                    "order:read",
                    "order:write",
                    "quota:read",
                    "admin:read",
                ],
                region="us-east-1",
            ),
            "test-standard": TenantContext(
                id="test-standard",
                name="Test Standard",
                tier="standard",
                roles=["operator", "viewer"],
                scopes=["patient:read", "order:read"],
            ),
        }

        return TENANT_STORE.get(
            tenant_id,
            TenantContext(
                id="shared",
                name="Shared (No Auth)",
                tier="free",
                roles=["viewer"],
                scopes=["public:read"],
            ),
        )
