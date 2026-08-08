"""FerreroMed MCP server (FastMCP 4.x).

This package provides an MCP server that wraps the FerreroMed REST API as:
- tools (operations)
- resources (OpenAPI, health)
- prompts (agent templates)
- apps (Prefab UI console)

It also includes gateway capabilities for hybrid local + remote MCP composition.

Implementation lives in `ferreromed_mcp.server`.
"""

from .server import create_mcp  # noqa: F401
