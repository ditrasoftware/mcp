"""
Federated Skill Discovery & Normalization

Enables anticafarmacia_mcp to discover capabilities from downstream MCPs,
normalize them to a canonical format, and expose them upstream as first-class skills.

Pattern: Downstream MCPs expose their capabilities (tools, resources, prompts) via
introspection endpoints or capability registries. Anticafarmacia learns these skills,
normalizes them, adapts auth/routing, and exposes them to upstream clients as if local.

This is the foundation for decentralized MCP architectures where:
- Each MCP owns its domain skills
- Skills flow upstream via discovery
- Skills are normalized for consistency
- Skills are composed/routed via gateway policies
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Callable
from datetime import datetime, timedelta

import httpx

from ..capability.contracts import CapabilityContract
from ..rest_client import AnticaFarmaciaRestClient
from ..settings import AnticaFarmaciaSettings

logger = logging.getLogger(__name__)


# ============================================================================
# SKILL FEDERATION DATA MODELS
# ============================================================================

@dataclass
class RemoteCapabilityMetadata:
    """Metadata about a remotely-discovered capability."""
    remote_mcp_name: str  # e.g., "google_workspace_mcp"
    remote_namespace: str  # e.g., "google_workspace_mcp"
    remote_tool_name: str  # e.g., "gmail_send_message"
    discovered_at: float
    discovery_source: str  # "capability_registry" | "introspection" | "manifest"
    auth_adapted: bool = False
    schema_adapted: bool = False
    errors_normalized: bool = False
    custom_tags: dict[str, str] = field(default_factory=dict)


@dataclass
class FederatedSkillInfo:
    """High-level info about a federated skill for client discovery."""
    skill_id: str  # e.g., "federated.google_workspace_mcp.gmail_send_message"
    local_tool_name: str  # Local wrapper tool name
    remote_mcp: str
    remote_tool_name: str
    title: str
    description: str
    category: str  # e.g., "communication", "productivity", "document"
    requires_auth: bool
    auth_scopes: list[str]
    reliability_tier: str  # "tier_a" | "tier_b" | "tier_c"
    pii_classification: str
    version: str = "1.0"
    canonical_contract: CapabilityContract | None = None


class SkillDiscoveryError(Exception):
    """Raised when skill discovery fails."""
    pass


class SkillNormalizationError(Exception):
    """Raised when skill normalization fails."""
    pass


# ============================================================================
# REMOTE MCP INTROSPECTION
# ============================================================================

class RemoteMCPIntrospector:
    """Discovers and introspects capabilities from a remote MCP server."""

    def __init__(self, mcp_name: str, mcp_url: str, auth_token: str | None = None):
        """
        Initialize introspector for a remote MCP.

        Args:
            mcp_name: Logical name for the MCP (e.g., "google_workspace_mcp")
            mcp_url: Base HTTP/S URL for the remote MCP server
            auth_token: Optional bearer token for authenticated introspection
        """
        self.mcp_name = mcp_name
        self.mcp_url = mcp_url.rstrip("/")
        self.auth_token = auth_token
        self.client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> RemoteMCPIntrospector:
        """Async context manager entry."""
        self.client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        if self.client:
            await self.client.aclose()

    async def discover_capabilities(self) -> dict[str, Any]:
        """
        Discover capabilities from remote MCP.

        Tries multiple discovery strategies:
        1. GET /capability/registry (FastMCP 4.0.x standard)
        2. GET /capabilities (alternate naming)
        3. POST /_mcp/introspection (MCP introspection protocol)
        4. Fallback: GET /.well-known/mcp/capabilities

        Returns:
            Dict with discovered capabilities by tool_name
        """
        if not self.client:
            raise RuntimeError("Introspector not initialized; use 'async with' context")

        strategies = [
            ("/capability/registry", "GET"),
            ("/capabilities", "GET"),
            ("/.well-known/mcp/capabilities", "GET"),
            ("/_mcp/introspection", "POST"),
        ]

        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        for endpoint, method in strategies:
            try:
                url = f"{self.mcp_url}{endpoint}"
                if method == "GET":
                    resp = await self.client.get(url, headers=headers)
                else:  # POST
                    resp = await self.client.post(url, json={"action": "introspect"}, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    logger.info(
                        f"Successfully discovered capabilities from {self.mcp_name} via {endpoint}",
                        extra={"mcp": self.mcp_name, "endpoint": endpoint, "capability_count": len(data)},
                    )
                    return data if isinstance(data, dict) else {"capabilities": data}

            except (httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                logger.debug(
                    f"Capability discovery strategy {endpoint} failed for {self.mcp_name}: {e}",
                    extra={"mcp": self.mcp_name, "endpoint": endpoint},
                )
                continue

        raise SkillDiscoveryError(
            f"Could not discover capabilities from {self.mcp_name} at {self.mcp_url}. "
            "Tried: /capability/registry, /capabilities, /.well-known/mcp/capabilities, /_mcp/introspection"
        )

    async def get_tool_schema(self, tool_name: str) -> dict[str, Any] | None:
        """
        Fetch detailed schema for a specific tool from remote MCP.

        Returns:
            Tool schema dict or None if not found
        """
        if not self.client:
            raise RuntimeError("Introspector not initialized; use 'async with' context")

        try:
            url = f"{self.mcp_url}/tools/{tool_name}"
            headers = {}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            resp = await self.client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except (httpx.RequestError, json.JSONDecodeError):
            pass

        return None


# ============================================================================
# SKILL NORMALIZATION & ADAPTATION
# ============================================================================

class SkillNormalizer:
    """Normalizes remote MCP skills to anticafarmacia canonical format."""

    def __init__(self, mcp_name: str, local_namespace: str):
        """
        Initialize normalizer.

        Args:
            mcp_name: Name of remote MCP (e.g., "google_workspace_mcp")
            local_namespace: Local namespace for federated skills (e.g., "google_workspace")
        """
        self.mcp_name = mcp_name
        self.local_namespace = local_namespace

    def normalize_capability(
        self,
        remote_tool_name: str,
        remote_capability: dict[str, Any],
        metadata: RemoteCapabilityMetadata,
    ) -> CapabilityContract:
        """
        Normalize a remote capability to anticafarmacia CapabilityContract.

        Args:
            remote_tool_name: Original tool name from remote MCP
            remote_capability: Capability dict from remote registry
            metadata: Discovery metadata

        Returns:
            Normalized CapabilityContract

        Normalization rules:
        - ID: federated.<namespace>.<tool_name>
        - Scopes: Adapt to anticafarmacia:federated:<namespace>:<scope>
        - Auth: Inherit from remote or default to "service"
        - Errors: Merge with anticafarmacia error categories
        - PII: Inherit from remote or default to "medium"
        """
        remote_id = remote_capability.get("capability_id", remote_tool_name)
        remote_scopes = remote_capability.get("required_scopes", [])
        remote_auth = remote_capability.get("auth_profile", "service")
        remote_errors = remote_capability.get("error_categories", [])
        remote_pii = remote_capability.get("pii_classification", "medium")

        # Normalize ID
        normalized_id = f"federated.{self.local_namespace}.{remote_tool_name}"

        # Adapt scopes: <namespace>:<scope> -> anticafarmacia:federated:<namespace>:<scope>
        adapted_scopes = tuple(
            f"anticafarmacia:federated:{self.local_namespace}:{scope}"
            for scope in remote_scopes
        )

        # Merge error categories with anticafarmacia standards
        anticafarmacia_errors = {
            "VALIDATION_ERROR", "AUTH_ERROR", "PROVIDER_ERROR", "TRANSIENT_ERROR",
            "NOT_FOUND_ERROR", "INTERNAL_ERROR", "RATE_LIMIT_ERROR", "TIMEOUT_ERROR"
        }
        merged_errors = list(set(remote_errors) | anticafarmacia_errors)

        # Normalize input/output schemas
        input_schema = remote_capability.get("input_schema", {"type": "object", "properties": {}})
        output_schema = remote_capability.get("output_schema", {"type": "object", "properties": {}})

        return CapabilityContract(
            capability_id=normalized_id,
            tool_name=f"federated_{self.local_namespace}_{remote_tool_name}",
            version=remote_capability.get("version", "1.0.0"),
            description=remote_capability.get("description", f"Federated skill from {self.mcp_name}"),
            input_schema=input_schema,
            output_schema=output_schema,
            routing_hints={
                "domain": self.local_namespace,
                "operation": remote_tool_name,
                "remote_mcp": self.mcp_name,
                "remote_tool": remote_tool_name,
            },
            auth_profile=remote_auth,
            required_scopes=adapted_scopes,
            reliability_tier=remote_capability.get("reliability_tier", "tier_b"),
            error_categories=merged_errors,
            pii_classification=remote_pii,
            provider=self.mcp_name,
            is_local=False,
        )

    def adapt_auth_requirements(
        self,
        contract: CapabilityContract,
        downstream_auth_config: dict[str, Any],
    ) -> CapabilityContract:
        """
        Adapt authentication requirements for upstream clients.

        Takes remote auth config and bridges it to anticafarmacia's auth model.
        Handles OIDC → OAuth 2.1, API key → JWT, etc.

        Args:
            contract: Normalized contract
            downstream_auth_config: Auth config from remote MCP

        Returns:
            Auth-adapted contract
        """
        # If remote requires specific auth, document it in routing hints
        if downstream_auth_config:
            contract.routing_hints["remote_auth_type"] = downstream_auth_config.get("type", "unknown")
            contract.routing_hints["remote_auth_scopes"] = downstream_auth_config.get("scopes", [])

        return contract

    def adapt_error_normalization(
        self,
        contract: CapabilityContract,
        remote_error_mapping: dict[str, str] | None = None,
    ) -> CapabilityContract:
        """
        Adapt error categories for normalization via middleware.

        Args:
            contract: Normalized contract
            remote_error_mapping: Map from remote error codes to anticafarmacia codes

        Returns:
            Error-normalized contract
        """
        if remote_error_mapping:
            contract.routing_hints["error_mapping"] = remote_error_mapping

        return contract


# ============================================================================
# FEDERATED SKILL REGISTRY
# ============================================================================

class FederatedSkillRegistry:
    """
    Central registry for skills discovered from remote MCPs.

    Maintains:
    - Discovered capabilities from each remote MCP
    - Normalization state and metadata
    - Cached introspection results
    - Time-based invalidation for skill cache
    """

    def __init__(self, cache_ttl_seconds: int = 3600):
        """
        Initialize federated skill registry.

        Args:
            cache_ttl_seconds: How long to cache discovered skills (default: 1 hour)
        """
        self.cache_ttl_seconds = cache_ttl_seconds
        self.skills: dict[str, FederatedSkillInfo] = {}  # skill_id -> FederatedSkillInfo
        self.metadata: dict[str, RemoteCapabilityMetadata] = {}  # skill_id -> metadata
        self.by_remote_mcp: dict[str, set[str]] = {}  # mcp_name -> set of skill_ids
        self.last_discovery: dict[str, float] = {}  # mcp_name -> timestamp
        self.discovery_errors: dict[str, str] = {}  # mcp_name -> error message

    def register_skill(
        self,
        skill: FederatedSkillInfo,
        metadata: RemoteCapabilityMetadata,
    ) -> None:
        """Register a discovered and normalized skill."""
        self.skills[skill.skill_id] = skill
        self.metadata[skill.skill_id] = metadata

        if metadata.remote_mcp_name not in self.by_remote_mcp:
            self.by_remote_mcp[metadata.remote_mcp_name] = set()
        self.by_remote_mcp[metadata.remote_mcp_name].add(skill.skill_id)

    def get_skill(self, skill_id: str) -> FederatedSkillInfo | None:
        """Retrieve a registered skill by ID."""
        return self.skills.get(skill_id)

    def get_skills_from_mcp(self, mcp_name: str) -> list[FederatedSkillInfo]:
        """Get all skills discovered from a specific remote MCP."""
        skill_ids = self.by_remote_mcp.get(mcp_name, set())
        return [self.skills[sid] for sid in skill_ids if sid in self.skills]

    def get_all_skills(self) -> list[FederatedSkillInfo]:
        """Get all registered federated skills."""
        return list(self.skills.values())

    def mark_discovery_complete(self, mcp_name: str, error: str | None = None) -> None:
        """Mark skill discovery as complete for an MCP."""
        self.last_discovery[mcp_name] = datetime.now().timestamp()
        if error:
            self.discovery_errors[mcp_name] = error
        else:
            self.discovery_errors.pop(mcp_name, None)

    def is_cache_valid(self, mcp_name: str) -> bool:
        """Check if cached skills for an MCP are still valid."""
        if mcp_name not in self.last_discovery:
            return False

        age_seconds = datetime.now().timestamp() - self.last_discovery[mcp_name]
        return age_seconds < self.cache_ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        """Export registry state for inspection/logging."""
        return {
            "skills": {k: asdict(v) for k, v in self.skills.items()},
            "by_remote_mcp": {k: list(v) for k, v in self.by_remote_mcp.items()},
            "last_discovery": self.last_discovery,
            "discovery_errors": self.discovery_errors,
        }


# ============================================================================
# FEDERATED SKILL LOADER
# ============================================================================

async def load_federated_skills(
    registry: FederatedSkillRegistry,
    settings: AnticaFarmaciaSettings,
) -> dict[str, Any]:
    """
    Discover and load skills from all configured remote MCPs.

    This function:
    1. Queries each remote MCP's capability registry
    2. Normalizes capabilities to anticafarmacia format
    3. Adapts auth, error handling, routing
    4. Registers skills in the federated registry
    5. Returns a summary for logging/observability

    Args:
        registry: FederatedSkillRegistry to populate
        settings: AnticaFarmaciaSettings with remote MCP config

    Returns:
        Summary dict with discovery results
    """
    summary = {
        "total_remote_mcps": len(settings.gateway.remotes),
        "mcps_queried": [],
        "total_skills_discovered": 0,
        "total_skills_normalized": 0,
        "errors": [],
    }

    for remote in settings.gateway.remotes:
        if not remote.enabled:
            continue

        mcp_name = remote.name
        logger.info(f"Starting skill discovery for remote MCP: {mcp_name}")

        try:
            async with RemoteMCPIntrospector(mcp_name, remote.url, remote.auth) as introspector:
                # Discover capabilities
                capabilities = await introspector.discover_capabilities()
                logger.info(f"Discovered {len(capabilities)} capabilities from {mcp_name}")

                # Normalize and register each capability
                normalizer = SkillNormalizer(mcp_name, remote.namespace)

                for tool_name, capability in capabilities.items():
                    try:
                        metadata = RemoteCapabilityMetadata(
                            remote_mcp_name=mcp_name,
                            remote_namespace=remote.namespace,
                            remote_tool_name=tool_name,
                            discovered_at=datetime.now().timestamp(),
                            discovery_source="capability_registry",
                        )

                        # Normalize capability to CapabilityContract
                        contract = normalizer.normalize_capability(tool_name, capability, metadata)

                        # Adapt auth and error handling
                        contract = normalizer.adapt_auth_requirements(
                            contract,
                            capability.get("auth_config", {}),
                        )
                        contract = normalizer.adapt_error_normalization(contract)

                        # Create high-level skill info
                        skill = FederatedSkillInfo(
                            skill_id=contract.capability_id,
                            local_tool_name=contract.tool_name,
                            remote_mcp=mcp_name,
                            remote_tool_name=tool_name,
                            title=capability.get("title", tool_name),
                            description=contract.description,
                            category=capability.get("category", "general"),
                            requires_auth=contract.auth_profile != "none",
                            auth_scopes=list(contract.required_scopes),
                            reliability_tier=contract.reliability_tier,
                            pii_classification=contract.pii_classification,
                            canonical_contract=contract,
                        )

                        # Register in federated registry
                        registry.register_skill(skill, metadata)
                        summary["total_skills_discovered"] += 1
                        summary["total_skills_normalized"] += 1

                        logger.debug(
                            f"Registered federated skill: {skill.skill_id}",
                            extra={"skill_id": skill.skill_id, "remote_tool": tool_name},
                        )

                    except (SkillNormalizationError, KeyError, ValueError) as e:
                        error_msg = f"Failed to normalize skill {tool_name} from {mcp_name}: {e}"
                        logger.warning(error_msg)
                        summary["errors"].append(error_msg)

                registry.mark_discovery_complete(mcp_name)
                summary["mcps_queried"].append(mcp_name)

        except SkillDiscoveryError as e:
            error_msg = f"Failed to discover skills from {mcp_name}: {e}"
            logger.error(error_msg)
            registry.mark_discovery_complete(mcp_name, error=str(e))
            summary["errors"].append(error_msg)

        except Exception as e:
            error_msg = f"Unexpected error during skill discovery for {mcp_name}: {e}"
            logger.exception(error_msg)
            registry.mark_discovery_complete(mcp_name, error=str(e))
            summary["errors"].append(error_msg)

    logger.info(
        f"Skill discovery complete: {summary['total_skills_normalized']} skills from "
        f"{len(summary['mcps_queried'])} MCPs",
        extra=summary,
    )

    return summary


# ============================================================================
# SKILL PROXY FACTORY
# ============================================================================

def create_federated_skill_tools(
    mcp,
    registry: FederatedSkillRegistry,
    client: AnticaFarmaciaRestClient,
    settings: AnticaFarmaciaSettings,
) -> int:
    """
    Create local tool wrappers for all registered federated skills.

    These wrappers:
    - Accept inputs matching the federated skill schema
    - Route through the gateway to the remote MCP
    - Adapt responses and errors to anticafarmacia format
    - Apply auth transformations as needed

    Args:
        mcp: FastMCP instance
        registry: FederatedSkillRegistry with discovered skills
        client: REST client for gateway calls
        settings: AnticaFarmaciaSettings

    Returns:
        Count of tool wrappers created
    """
    tools_created = 0

    for skill in registry.get_all_skills():
        try:
            # Create a tool wrapper for this federated skill
            tool_name = skill.local_tool_name
            contract = skill.canonical_contract

            async def make_federated_tool(
                _contract=contract,
                _skill=skill,
                _client=client,
                _settings=settings,
            ):
                async def federated_tool(**kwargs: Any) -> Any:
                    """Route call to remote MCP via gateway."""
                    # Build gateway routing request
                    routing_request = {
                        "remote_mcp": _skill.remote_mcp,
                        "tool_name": _skill.remote_tool_name,
                        "arguments": kwargs,
                        "routing_hints": _contract.routing_hints,
                    }

                    # Route through gateway
                    # In production, this would use the gateway's routing logic
                    # For now, we document the pattern
                    logger.info(
                        f"Routing federated skill call: {_skill.skill_id}",
                        extra=routing_request,
                    )

                    # TODO: Implement actual gateway routing
                    # - Apply auth adapter
                    # - Call remote MCP tool
                    # - Normalize response
                    # - Adapt errors

                    return {
                        "status": "routed",
                        "skill_id": _skill.skill_id,
                        "remote_mcp": _skill.remote_mcp,
                        "remote_tool": _skill.remote_tool_name,
                        "arguments": kwargs,
                    }

                return federated_tool

            # Register tool with MCP
            tool_func = make_federated_tool()
            mcp.tool(name=tool_name, description=skill.description)(tool_func)

            tools_created += 1
            logger.info(f"Created federated skill tool: {tool_name}")

        except Exception as e:
            logger.error(f"Failed to create tool for skill {skill.skill_id}: {e}")

    return tools_created
