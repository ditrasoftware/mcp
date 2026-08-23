"""Backward-compatible wrapper for local tool registration.

Use servers.ditrasoftware_template_mcp.artifacts.tools.local instead.
"""

from ..artifacts.tools.local import register_local_tools

__all__ = ["register_local_tools"]
