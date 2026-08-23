"""
Skill Federation Integration - Server Startup

Integrates federated skill discovery into anticafarmacia_mcp server startup.
This module orchestrates the discovery, normalization, and exposure of skills
from downstream MCPs (like google_workspace_mcp) to upstream clients.

Integration points:
1. Server initialization: load_federated_skills_on_startup()
2. Middleware: Add skill discovery results to observability
3. Tool registration: Create proxies for federated skills
4. Resource endpoint: Expose skill registry via HTTP for clients
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..rest_client import AnticaFarmaciaRestClient
from ..settings import AnticaFarmaciaSettings
from .skill_federation import (
    FederatedSkillRegistry,
    load_federated_skills,
    create_federated_skill_tools,
)

logger = logging.getLogger(__name__)


async def initialize_federated_skills(
    mcp: FastMCP,
    client: AnticaFarmaciaRestClient,
    settings: AnticaFarmaciaSettings,
) -> FederatedSkillRegistry:
    """
    Initialize federated skill discovery at server startup.

    This is called early in the server lifecycle to:
    1. Create the federated skill registry
    2. Discover capabilities from all enabled remote MCPs
    3. Normalize skills to canonical format
    4. Register tool proxies with the MCP
    5. Expose skill registry via resources

    Args:
        mcp: FastMCP server instance
        client: REST client for backend calls
        settings: Server settings with remote MCP configuration

    Returns:
        Populated FederatedSkillRegistry

    Note:
        Failures during skill discovery are logged but do not block server startup.
        This allows the server to function even if downstream MCPs are unavailable.
    """
    registry = FederatedSkillRegistry(
        cache_ttl_seconds=settings.cache_ttl or 3600
    )

    # Skip if no remote MCPs configured
    if not settings.gateway.remotes:
        logger.info("No remote MCPs configured; skipping federated skill discovery")
        return registry

    # Discover and load skills from all remote MCPs
    logger.info(
        f"Starting federated skill discovery for {len(settings.gateway.remotes)} remote MCPs"
    )

    discovery_summary = await load_federated_skills(registry, settings)

    logger.info(
        f"Federated skill discovery complete: "
        f"{discovery_summary['total_skills_normalized']} skills normalized, "
        f"{len(discovery_summary['errors'])} errors",
        extra=discovery_summary,
    )

    # Create tool proxies for discovered skills
    if registry.get_all_skills():
        tools_created = create_federated_skill_tools(mcp, registry, client, settings)
        logger.info(
            f"Created {tools_created} tool proxies for federated skills",
            extra={"tools_created": tools_created},
        )

    # Register resource endpoint for skill registry
    @mcp.resource("anticafarmacia://skills/federated/registry")
    async def federated_skills_registry_resource() -> dict[str, Any]:
        """
        Expose federated skill registry for client introspection.

        Returns:
            JSON representation of all discovered federated skills
        """
        return {
            "schema_version": "1.0",
            "registry_type": "federated",
            "timestamp": __import__("time").time(),
            "summary": {
                "total_skills": len(registry.get_all_skills()),
                "by_remote_mcp": {
                    mcp_name: len(skills)
                    for mcp_name, skills in {
                        mcp_name: registry.get_skills_from_mcp(mcp_name)
                        for mcp_name in set(
                            m.remote_mcp for m in registry.get_all_skills()
                        )
                    }.items()
                },
            },
            "skills": [
                {
                    "skill_id": skill.skill_id,
                    "local_tool_name": skill.local_tool_name,
                    "remote_mcp": skill.remote_mcp,
                    "remote_tool_name": skill.remote_tool_name,
                    "title": skill.title,
                    "description": skill.description,
                    "category": skill.category,
                    "requires_auth": skill.requires_auth,
                    "auth_scopes": skill.auth_scopes,
                    "reliability_tier": skill.reliability_tier,
                    "pii_classification": skill.pii_classification,
                }
                for skill in registry.get_all_skills()
            ],
            "discovery_status": {
                "mcps_queried": list(registry.last_discovery.keys()),
                "errors": registry.discovery_errors,
            },
        }

    return registry


def add_skill_federation_middleware(
    mcp: FastMCP,
    registry: FederatedSkillRegistry,
) -> None:
    """
    Add middleware to track skill federation observability.

    Logs skill discovery metrics, errors, and routing decisions
    for monitoring and debugging.

    Args:
        mcp: FastMCP server instance
        registry: FederatedSkillRegistry
    """

    original_handle_tool_call = mcp.handle_tool_call

    async def handle_tool_call_with_federation_tracking(
        name: str, arguments: dict[str, Any]
    ) -> Any:
        """Wrapper around tool calls to track federated skill usage."""
        # Check if this is a federated tool
        for skill in registry.get_all_skills():
            if name == skill.local_tool_name:
                logger.info(
                    f"Federated skill call: {skill.skill_id}",
                    extra={
                        "skill_id": skill.skill_id,
                        "local_tool": name,
                        "remote_mcp": skill.remote_mcp,
                        "remote_tool": skill.remote_tool_name,
                    },
                )
                break

        return await original_handle_tool_call(name, arguments)

    # Note: In FastMCP, direct middleware injection may vary
    # This is a pattern template; actual implementation depends on FastMCP API


def create_skill_federation_summary_tool(
    mcp: FastMCP,
    registry: FederatedSkillRegistry,
) -> None:
    """
    Register a tool that summarizes available federated skills.

    Allows clients (like Claude) to ask: "What skills do we have from google_workspace_mcp?"

    Args:
        mcp: FastMCP server instance
        registry: FederatedSkillRegistry
    """

    @mcp.tool()
    async def list_federated_skills(
        filter_by_remote_mcp: str | None = None,
        filter_by_category: str | None = None,
    ) -> dict[str, Any]:
        """
        List available federated skills from downstream MCPs.

        Args:
            filter_by_remote_mcp: Optional MCP name to filter (e.g., "google_workspace_mcp")
            filter_by_category: Optional category to filter (e.g., "communication")

        Returns:
            Dict with filtered skill list and metadata
        """
        all_skills = registry.get_all_skills()

        if filter_by_remote_mcp:
            all_skills = [s for s in all_skills if s.remote_mcp == filter_by_remote_mcp]

        if filter_by_category:
            all_skills = [s for s in all_skills if s.category == filter_by_category]

        return {
            "total_available": len(all_skills),
            "filters_applied": {
                "remote_mcp": filter_by_remote_mcp,
                "category": filter_by_category,
            },
            "skills": [
                {
                    "skill_id": skill.skill_id,
                    "title": skill.title,
                    "description": skill.description,
                    "category": skill.category,
                    "remote_mcp": skill.remote_mcp,
                    "local_tool_name": skill.local_tool_name,
                    "requires_auth": skill.requires_auth,
                }
                for skill in all_skills
            ],
        }
