from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillProvider

from ...rest_client import LottomaticapssRestClient
from ...settings import LottomaticapssSettings
from ...metabase_client import MetabaseClient

BUSINESS_SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "lottomatica-pss" / "SKILL.md"
BUSINESS_SKILL_URI = "skill://lottomatica-pss/SKILL.md"


def register_local_resources(
    mcp: FastMCP,
    client: LottomaticapssRestClient,
    metabase_client: MetabaseClient | None = None,
) -> dict[str, Any]:
    """Register domain-specific local resources."""

    local_resource_registry: dict[str, Any] = {}
    mcp.add_provider(SkillProvider(BUSINESS_SKILL_PATH.parent))
    local_resource_registry[BUSINESS_SKILL_URI] = BUSINESS_SKILL_URI
    manifest_uri = "skill://lottomatica-pss/_manifest"
    local_resource_registry[manifest_uri] = manifest_uri

    @mcp.resource(uri="ditra-analytics://config")
    async def config_resource() -> dict[str, Any]:
        """Non-secret Ditra Analytics connection configuration."""
        mb = metabase_client.settings if metabase_client else None
        if mb is None:
            return {"configured": False}
        return {
            "configured": True,
            "site_url": mb.site_url,
            "mcp_url": mb.mcp_url,
            "access_mode": mb.access_mode,
            "api_fallback_enabled": mb.api_fallback_enabled,
            "default_page_size": mb.default_page_size,
            "max_page_size": mb.max_page_size,
            "default_dashboard_id": mb.default_dashboard_id,
            "default_collection_id": mb.default_collection_id,
            "api_key_configured": bool(mb.api_key),
            "username_configured": bool(mb.username),
            "embedding_secret_configured": bool(mb.embedding_secret_key),
            "tool_alias_policy": {
                "hashed_aliases": os.getenv("DITRASOFTWARE_HASHED_TOOL_ALIASES", "auto"),
                "legacy_hashed_aliases": os.getenv(
                    "DITRASOFTWARE_LEGACY_HASHED_ALIASES", "auto"
                ),
                "purpose": "Client compatibility aliases; not stored artifacts",
            },
        }

    local_resource_registry["ditra-analytics://config"] = "ditra-analytics://config"

    @mcp.resource(uri="ditra-analytics://dashboard-summary")
    async def dashboard_summary_resource() -> dict[str, Any]:
        """Summary of the default Ditra Analytics dashboard (Lottomatica PSS Dashboard)."""
        if metabase_client is None:
            return {"configured": False}
        response = await metabase_client.get_dashboard(
            metabase_client.settings.default_dashboard_id
        )
        dashboard = response.data
        dashcards = dashboard.get("dashcards", []) if isinstance(dashboard, dict) else []
        return {
            "id": dashboard.get("id") if isinstance(dashboard, dict) else None,
            "name": dashboard.get("name") if isinstance(dashboard, dict) else None,
            "collection_id": dashboard.get("collection_id") if isinstance(dashboard, dict) else None,
            "card_count": len(dashcards),
            "backend": response.backend,
        }

    local_resource_registry["ditra-analytics://dashboard-summary"] = "ditra-analytics://dashboard-summary"

    return local_resource_registry
