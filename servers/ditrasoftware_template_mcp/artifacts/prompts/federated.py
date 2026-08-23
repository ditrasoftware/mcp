"""Federated prompt registrations.

This module is reserved for prompts sourced from remote MCPs or shared prompt packs.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_federated_prompts(mcp: FastMCP, **kwargs) -> set[str]:
    """Register remote/federated prompts."""
    return set()
