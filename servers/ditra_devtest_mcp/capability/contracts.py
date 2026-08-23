"""Capability contract definitions.

Provides CapabilityContract dataclass for all artifacts (tools, resources, prompts).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityContract:
    """Canonical contract for a capability.

    Describes a tool, resource, or prompt with metadata for discovery,
    routing, auth, and resilience.
    """

    # Identity
    capability_id: str  # e.g., "patient.search", "order.create"
    tool_name: str  # e.g., "local_patient_search" or "google_workspace.patient.search"
    version: str
    description: str

    # Schema
    input_schema: dict[str, Any]  # JSON Schema
    output_schema: dict[str, Any]  # JSON Schema
    aliases: dict[str, str] = field(default_factory=dict)  # param name mappings

    # FastMCP 4.0.x routing
    mcp_name: str | None = None  # MCP routing name
    mcp_method: str | None = None  # MCP method hint
    routing_hints: dict[str, str] = field(default_factory=dict)

    # Enterprise metadata
    auth_profile: str = "none"  # "none" | "user" | "service"
    required_scopes: list[str] = field(default_factory=list)
    reliability_tier: str = "tier_b"  # "tier_a" | "tier_b" | "tier_c"
    error_categories: list[str] = field(default_factory=list)
    pii_classification: str = "none"  # "none" | "low" | "high"

    # Resource caching (for @mcp.resource)
    cache_control: str | None = None  # e.g., "max-age=300"
    resource_streaming: bool = False

    # Fallback behavior
    fallback_mode: str = "none"  # "none" | "local_alternative" | "cached"
    fallback_response: dict[str, Any] | None = None

    @property
    def is_local(self) -> bool:
        """Whether this capability is implemented locally."""
        return self.tool_name.startswith("local_")

    @property
    def provider(self) -> str | None:
        """Extract provider from tool_name (e.g., 'google_workspace' from 'google_workspace.patient.search')."""
        if self.is_local:
            return None
        parts = self.tool_name.split(".")
        return parts[0] if parts else None

    def validate(self) -> list[str]:
        """Validate contract completeness. Returns list of warnings."""
        warnings = []
        
        if not self.capability_id:
            warnings.append("capability_id is required")
        if not self.tool_name:
            warnings.append("tool_name is required")
        if self.auth_profile != "none" and not self.required_scopes:
            warnings.append(f"auth_profile={self.auth_profile} but no required_scopes")
        if not self.error_categories:
            warnings.append("error_categories should be specified")
        
        return warnings
