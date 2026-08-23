"""Backward-compatible provider imports.

Canonical artifact entrypoints now live under the artifacts package.
"""

from ..artifacts import (
    create_local_app_providers,
    register_local_prompts,
    register_local_resources,
    register_local_tools,
)

__all__ = [
    "register_local_tools",
    "register_local_resources",
    "register_local_prompts",
    "create_local_app_providers",
]
