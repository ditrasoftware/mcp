"""Artifact registration entrypoints organized by type and source."""

from .tools.local import register_local_tools
from .resources.local import register_local_resources
from .prompts.local import register_local_prompts
from .apps.local import create_local_app_providers

__all__ = [
    "register_local_tools",
    "register_local_resources",
    "register_local_prompts",
    "create_local_app_providers",
]
