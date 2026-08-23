"""Federated prompt registrations.

Reserved for prompts from shared or remote prompt packs.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_federated_prompts(mcp: FastMCP, **kwargs) -> set[str]:
    """Register remote/federated prompts."""
    return set()
