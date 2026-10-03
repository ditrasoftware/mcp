"""Federated prompt registrations.

Reserved for remote/adapter-backed prompts.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def register_federated_prompts(mcp: FastMCP, **kwargs) -> dict[str, Any]:
    """Register remote/federated prompts."""
    return {}
