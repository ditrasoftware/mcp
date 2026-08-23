"""Federated resource registrations.

Reserved for remote/adapter-backed resources.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_federated_resources(mcp: FastMCP, **kwargs) -> set[str]:
    """Register remote/federated resources."""
    return set()
