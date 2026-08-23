"""Capability contract dataclass template."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityContract:
    """Canonical contract for a capability (tool, resource, or prompt).
    
    Customize for your domain-specific metadata.
    """

    # Identity
    capability_id: str
    tool_name: str
    version: str
    description: str

    # Schema
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    aliases: dict[str, str] = field(default_factory=dict)

    # FastMCP 4.0.x routing
    mcp_name: str | None = None
    routing_hints: dict[str, str] = field(default_factory=dict)

    # Enterprise metadata
    auth_profile: str = "none"
    required_scopes: list[str] = field(default_factory=list)
    reliability_tier: str = "tier_b"
    error_categories: list[str] = field(default_factory=list)
    pii_classification: str = "none"

    # Resource caching
    cache_control: str | None = None

    @property
    def is_local(self) -> bool:
        return self.tool_name.startswith("local_")

    @property
    def provider(self) -> str | None:
        if self.is_local:
            return None
        parts = self.tool_name.split(".")
        return parts[0] if parts else None

    def validate(self) -> list[str]:
        """Validate contract. Returns warnings."""
        warnings = []
        if not self.capability_id:
            warnings.append("capability_id required")
        if self.auth_profile != "none" and not self.required_scopes:
            warnings.append("auth_profile set but no required_scopes")
        return warnings
