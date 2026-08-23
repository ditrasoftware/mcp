"""Capability registry template.

TODO: Replace with your capabilities.
"""

from .contracts import CapabilityContract


# TODO: Define your capabilities here
CAPABILITIES: dict[str, CapabilityContract] = {
    "example.tool": CapabilityContract(
        capability_id="example.tool",
        tool_name="local_example_tool",
        version="1.0",
        description="An example tool to customize",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        auth_profile="none",
        reliability_tier="tier_a",
        error_categories=["VALIDATION_ERROR"],
    ),
}


def load_capability_registry() -> dict[str, CapabilityContract]:
    """Load and validate capability registry."""
    
    for cap_id, contract in CAPABILITIES.items():
        warnings = contract.validate()
        if warnings:
            print(f"Warning: {cap_id}: {warnings}")
    
    return CAPABILITIES


def get_capability(capability_id: str) -> CapabilityContract | None:
    """Look up a capability."""
    return CAPABILITIES.get(capability_id)


def get_local_capabilities() -> list[CapabilityContract]:
    """Get locally-implemented capabilities."""
    return [c for c in CAPABILITIES.values() if c.is_local]
