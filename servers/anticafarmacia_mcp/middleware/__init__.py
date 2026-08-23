"""Enterprise MCP middleware stack for ditra_devtest_mcp.

Middleware implements cross-cutting concerns:
- Tenant resolution from auth/headers
- Auth enforcement and token refresh
- Error normalization to standard taxonomy
- Observability (request-id, metrics, audit)
- Policy-driven route decisions (local vs remote)
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
