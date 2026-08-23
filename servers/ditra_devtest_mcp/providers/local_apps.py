"""Backward-compatible wrapper for local app provider registration.

Use servers.ditra_devtest_mcp.artifacts.apps.local instead.
"""

from ..artifacts.apps.local import create_local_app_providers

__all__ = ["create_local_app_providers"]
