"""Enterprise MCP middleware stack template.

Copy this to your new MCP and customize as needed.
"""

from .tenant_resolution import TenantResolutionMiddleware
from .auth_enforcement import AuthEnforcementMiddleware
from .error_normalization import ErrorNormalizationMiddleware
from .observability import ObservabilityMiddleware

__all__ = [
    "TenantResolutionMiddleware",
    "AuthEnforcementMiddleware",
    "ErrorNormalizationMiddleware",
    "ObservabilityMiddleware",
]
