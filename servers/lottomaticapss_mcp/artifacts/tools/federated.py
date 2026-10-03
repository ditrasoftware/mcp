"""Federated tool registrations.

Reserved for remote/adapter-backed tools.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_federated_tools(mcp: FastMCP, **kwargs) -> set[str]:
    """Register remote/federated tools."""
    return set()
