"""Capability registry for anticafarmacia_mcp.

Defines local capability contracts exposed by this MCP.
"""

from __future__ import annotations

from .contracts import CapabilityContract
from ..version import __version__


CAPABILITIES: dict[str, CapabilityContract] = {
    "local.auth.debug": CapabilityContract(
        capability_id="local.auth.debug",
        tool_name="local_auth_debug",
        version=__version__,
        description="Inspect authentication headers (non-sensitive)",
        input_schema={"type": "object", "properties": {}},
        output_schema={
            "type": "object",
            "properties": {
                "has_authorization": {"type": "boolean"},
                "authorization_scheme": {"type": "string"},
            },
        },
        auth_profile="none",
        reliability_tier="tier_a",
        error_categories=["INTERNAL_ERROR", "AUTH_ERROR"],
    ),
    
    "local.gateway.summary": CapabilityContract(
        capability_id="local.gateway.summary",
        tool_name="local_gateway_summary",
        version=__version__,
        description="Return gateway configuration and remote MCP status",
        input_schema={"type": "object", "properties": {}},
        output_schema={
            "type": "object",
            "properties": {
                "gateway_mode": {"type": "string"},
                "remotes": {"type": "array"},
            },
        },
        auth_profile="none",
        reliability_tier="tier_a",
        error_categories=["INTERNAL_ERROR"],
    ),

    "local.api.get": CapabilityContract(
        capability_id="local.api.get",
        tool_name="local_api_get",
        version=__version__,
        description="Proxy GET request to AnticaFarmacia REST backend",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "query": {"type": "object", "default": {}},
                "access_token": {"type": "string"},
                "api_key": {"type": "string"},
            },
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
        auth_profile="service",
        required_scopes=["api:read"],
        reliability_tier="tier_b",
        error_categories=["VALIDATION_ERROR", "AUTH_ERROR", "PROVIDER_ERROR", "TRANSIENT_ERROR"],
        pii_classification="low",
    ),

    "local.api.post": CapabilityContract(
        capability_id="local.api.post",
        tool_name="local_api_post",
        version=__version__,
        description="Proxy POST request to AnticaFarmacia REST backend",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "payload": {"type": "object"},
                "access_token": {"type": "string"},
                "api_key": {"type": "string"},
            },
            "required": ["path", "payload"],
        },
        output_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
        auth_profile="service",
        required_scopes=["api:write"],
        reliability_tier="tier_a",
        error_categories=["VALIDATION_ERROR", "AUTH_ERROR", "PROVIDER_ERROR", "TRANSIENT_ERROR"],
        pii_classification="medium",
    ),

    "local.api.delete": CapabilityContract(
        capability_id="local.api.delete",
        tool_name="local_api_delete",
        version=__version__,
        description="Proxy DELETE request to AnticaFarmacia REST backend",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "access_token": {"type": "string"},
                "api_key": {"type": "string"},
            },
            "required": ["path"],
        },
        output_schema={
            "type": "string",
        },
        auth_profile="service",
        required_scopes=["api:write"],
        reliability_tier="tier_a",
        error_categories=["VALIDATION_ERROR", "AUTH_ERROR", "PROVIDER_ERROR", "NOT_FOUND_ERROR"],
        pii_classification="low",
    ),
}


def load_capability_registry() -> dict[str, CapabilityContract]:
    """Load and validate capability registry.
    
    In production, this might load from:
    - JSON configuration file
    - Database
    - Remote registry service
    
    For now, returns the hardcoded CAPABILITIES.
    """
    
    # Validate all capabilities
    for cap_id, contract in CAPABILITIES.items():
        warnings = contract.validate()
        if warnings:
            print(f"Warning: capability {cap_id} has issues: {warnings}")
    
    return CAPABILITIES


def get_capability(capability_id: str) -> CapabilityContract | None:
    """Look up a capability by ID."""
    return CAPABILITIES.get(capability_id)


def get_capabilities_by_provider(provider: str | None) -> list[CapabilityContract]:
    """Get all capabilities from a provider (or local if provider is None)."""
    return [
        c for c in CAPABILITIES.values()
        if c.provider == provider
    ]


def get_local_capabilities() -> list[CapabilityContract]:
    """Get all locally-implemented capabilities."""
    return [c for c in CAPABILITIES.values() if c.is_local]
