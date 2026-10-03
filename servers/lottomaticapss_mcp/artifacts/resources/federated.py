"""Federated resource registrations.

Reserved for remote/adapter-backed resources.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def register_federated_resources(mcp: FastMCP, **kwargs) -> dict[str, Any]:
    """Register remote/federated resources."""
    return {}
