"""Federated resource registrations.

This module is reserved for resources backed by remote MCP adapters.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_federated_resources(mcp: FastMCP, **kwargs) -> set[str]:
    """Register remote/federated resources."""
    return set()
