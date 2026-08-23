"""Capability contracts and registry for ditra_devtest_mcp.

Provides:
- CapabilityContract dataclass
- Error taxonomy
- Registry loading/validation
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
