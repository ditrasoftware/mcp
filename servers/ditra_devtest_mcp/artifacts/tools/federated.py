"""Federated tool registrations.

This module is reserved for tool registrations backed by remote MCP adapters.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_federated_tools(mcp: FastMCP, **kwargs) -> set[str]:
    """Register remote/federated tools.

    Keep local tools in local.py and remote adapter-backed tools here.
    """
    return set()
