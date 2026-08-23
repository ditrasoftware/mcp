"""Backward-compatible wrapper for local resource registration.

Use servers.ditra_devtest_mcp.artifacts.resources.local instead.
"""

from ..artifacts.resources.local import register_local_resources

__all__ = ["register_local_resources"]
