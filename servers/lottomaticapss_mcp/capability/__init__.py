"""Capability contracts and registry for lottomaticapss_mcp.

Provides:
- CapabilityContract dataclass
- Error taxonomy
- Registry loading/validation
"""

from .contracts import CapabilityContract
from .error_taxonomy import ERROR_CATEGORIES, ERROR_TAXONOMY
from .registry import CAPABILITIES, get_capability, get_local_capabilities, load_capability_registry

__all__ = [
    "CapabilityContract",
    "ERROR_CATEGORIES",
    "ERROR_TAXONOMY",
    "CAPABILITIES",
    "get_capability",
    "get_local_capabilities",
    "load_capability_registry",
]
