"""Backward-compatible wrapper for local prompt registration.

Use servers.anticafarmacia_mcp.artifacts.prompts.local instead.
"""

from ..artifacts.prompts.local import register_local_prompts

__all__ = ["register_local_prompts"]
