"""Backward-compatible wrapper for local tool registration.

Use servers.ditra_devtest_mcp.artifacts.tools.local instead.
"""

from ..artifacts.tools.local import register_local_tools

__all__ = ["register_local_tools"]
