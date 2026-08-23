"""Backward-compatible wrapper for local resource registration.

Use servers.ditrasoftware_template_mcp.artifacts.resources.local instead.
"""

from ..artifacts.resources.local import register_local_resources

__all__ = ["register_local_resources"]
