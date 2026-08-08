"""DitraSoftware MCP Template (FastMCP 4.x).

This package provides a base scaffolding for DitraSoftware MCP servers.
It includes generic infrastructure for REST API integration, gateway capabilities,
and UI console.

Domain-specific implementation (tools, resources, prompts) should be added by
extending the local_tools, local_resources, and local_prompts modules.

Implementation lives in `server.py` and the `providers/` directory.
"""

from .server import create_mcp  # noqa: F401
