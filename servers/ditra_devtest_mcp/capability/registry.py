"""Capability registry for ditra_devtest_mcp.

Defines all capabilities exposed by this MCP, both local and remote.
Acts as source of truth for discovery, routing, and policy.
"""

from __future__ import annotations

from .contracts import CapabilityContract


# Local capabilities (implemented in this MCP)
CAPABILITIES: dict[str, CapabilityContract] = {
    # Diagnostic tools
    "local.auth.debug": CapabilityContract(
        capability_id="local.auth.debug",
        tool_name="local_auth_debug",
        version="1.0",
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
        error_categories=["INTERNAL_ERROR"],
    ),
    
    "local.gateway.summary": CapabilityContract(
        capability_id="local.gateway.summary",
        tool_name="local_gateway_summary",
        version="1.0",
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
    
    # Remote capabilities (proxied to downstream MCPs)
    # These are placeholder examples; real impl would load from downstream adapters
    "patient.search": CapabilityContract(
        capability_id="patient.search",
        tool_name="local_patient_search",  # Will be routed to remote adapter
        version="1.0",
        description="Search for patients",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "patients": {"type": "array"},
                "total": {"type": "integer"},
            },
        },
        routing_hints={"domain": "patient", "operation": "search"},
        auth_profile="user",
        required_scopes=["patient:read"],
        reliability_tier="tier_b",
        error_categories=["VALIDATION_ERROR", "AUTH_ERROR", "PROVIDER_ERROR", "TRANSIENT_ERROR"],
        pii_classification="high",
    ),
    
    "order.create": CapabilityContract(
        capability_id="order.create",
        tool_name="local_order_create",
        version="1.0",
        description="Create a new order",
        input_schema={
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "items": {"type": "array"},
                "delivery_address": {"type": "string"},
            },
            "required": ["patient_id", "items"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "status": {"type": "string"},
            },
        },
        routing_hints={"domain": "order", "operation": "create"},
        auth_profile="user",
        required_scopes=["order:write"],
        reliability_tier="tier_a",
        error_categories=["VALIDATION_ERROR", "AUTH_ERROR", "PROVIDER_ERROR"],
        pii_classification="high",
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
