"""Capability contracts and registry template.

TODO: Customize CAPABILITIES dict with your own capabilities.
"""

from .contracts import CapabilityContract
from .error_taxonomy import ERROR_CATEGORIES, ERROR_TAXONOMY
from .registry import CAPABILITIES, load_capability_registry

__all__ = [
    "CapabilityContract",
    "ERROR_CATEGORIES",
    "ERROR_TAXONOMY",
    "CAPABILITIES",
    "load_capability_registry",
]
