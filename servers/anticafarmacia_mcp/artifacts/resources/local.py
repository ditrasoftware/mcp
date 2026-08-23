from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ...rest_client import AnticaFarmaciaRestClient
from ...settings import AnticaFarmaciaSettings


def register_local_resources(
    mcp: FastMCP,
    client: AnticaFarmaciaRestClient,
    settings: AnticaFarmaciaSettings,
) -> dict[str, Any]:
    """Register AnticaFarmacia resources."""

    @mcp.resource("anticafarmacia://health")
    async def anticafarmacia_health_resource() -> dict[str, Any]:
        """Static health/config view useful during client bootstrapping."""
        return {
            "service": "AnticaFarmacia MCP",
            "api_base_url_configured": bool(client.base_url),
            "gateway_mode": settings.gateway.mode,
            "route_policy": settings.gateway.route_policy,
            "configured_remotes": len(settings.gateway.remotes),
        }

    @mcp.resource("anticafarmacia://gateway/remotes")
    async def anticafarmacia_gateway_remotes_resource() -> dict[str, Any]:
        """Current remote backend configuration."""
        return {
            "remotes": [
                {
                    "name": remote.name,
                    "namespace": remote.namespace,
                    "type": remote.type,
                    "url": remote.url,
                    "enabled": remote.enabled,
                    "init_timeout_ms": remote.init_timeout_ms,
                    "timeout_ms": remote.timeout_ms,
                }
                for remote in settings.gateway.remotes
            ]
        }

    @mcp.resource("anticafarmacia://security/profile")
    async def anticafarmacia_security_profile_resource() -> dict[str, Any]:
        """High-level auth and security toggles."""
        return {
            "oidc_enabled": settings.oidc.enabled,
            "pkce_enabled": settings.pkce.enabled,
            "dpop_enabled": settings.dpop.enabled,
            "gcip_enabled": settings.gcip.enabled,
            "tenant_enabled": settings.tenant.enabled,
            "rbac_enabled": settings.rbac.enabled,
            "audit_enabled": settings.audit.enabled,
            "token_rotation_enabled": settings.token.rotation_enabled,
        }

    return {
        "uris": [
            "anticafarmacia://health",
            "anticafarmacia://gateway/remotes",
            "anticafarmacia://security/profile",
        ]
    }
