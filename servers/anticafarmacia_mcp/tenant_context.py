"""Tenant context extraction and forwarding for multi-tenant MCP architecture.

Handles:
- Extracting tenant ID from OAuth/OIDC ID token
- Validating tenant isolation
- Forwarding tenant context to downstream MCPs via headers
- Enforcing tenant-scoped access
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastmcp.server.context import Context
from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


@dataclass
class TenantContext:
    """Tenant security context."""
    tenant_id: str
    tenant_name: str | None = None
    org_id: str | None = None
    roles: list[str] | None = None
    scopes: list[str] | None = None
    namespace: str | None = None  # Isolated namespace for downstream MCPs


class TenantContextManager:
    """Extract and manage tenant context from OAuth tokens."""
    
    def __init__(
        self,
        extract_claim: str = "tenant_id",
        fallback_claims: list[str] | None = None,
        enforce_isolation: bool = False,
    ):
        """Initialize tenant manager.
        
        Args:
            extract_claim: Primary JWT claim for tenant ID
            fallback_claims: Alternative claims if primary missing
            enforce_isolation: Require tenant_id for all operations
        """
        self.extract_claim = extract_claim
        self.fallback_claims = fallback_claims or ["org_id", "organization_id", "organizations"]
        self.enforce_isolation = enforce_isolation
    
    def extract_from_token(self, id_token_payload: dict[str, Any]) -> TenantContext | None:
        """Extract tenant context from ID token.
        
        Args:
            id_token_payload: Decoded JWT claims
        
        Returns:
            TenantContext or None if not found
        """
        tenant_id = self._extract_tenant_id(id_token_payload)
        if not tenant_id:
            if self.enforce_isolation:
                raise ToolError(f"Tenant context required (claim: {self.extract_claim})")
            return None
        
        # Extract optional tenant metadata
        tenant_name = id_token_payload.get("tenant_name")
        org_id = id_token_payload.get("org_id") or id_token_payload.get("organization_id")
        
        # Extract roles (GCIP uses 'groups' or 'roles')
        roles = []
        if "groups" in id_token_payload:
            groups = id_token_payload.get("groups", [])
            roles.extend(g for g in groups if isinstance(g, str))
        if "roles" in id_token_payload:
            role_list = id_token_payload.get("roles", [])
            roles.extend(r for r in role_list if isinstance(r, str))
        
        # Extract scopes
        scopes = []
        scope_str = id_token_payload.get("scope", "")
        if isinstance(scope_str, str):
            scopes = [s.strip() for s in scope_str.split() if s.strip()]
        
        # Derive namespace from tenant_id (e.g., "acme" -> "acme_mcp")
        namespace = f"{tenant_id.lower().replace('-', '_')}_mcp"
        
        context = TenantContext(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            org_id=org_id,
            roles=roles if roles else None,
            scopes=scopes if scopes else None,
            namespace=namespace,
        )
        
        logger.debug(f"Tenant context extracted: {context.tenant_id} ({context.org_id})")
        return context
    
    def extract_from_context(self, ctx: Context | None) -> TenantContext | None:
        """Extract tenant context from MCP request context.
        
        Looks for:
        - X-Tenant-ID header
        - Authorization token claims
        
        Args:
            ctx: FastMCP request context
        
        Returns:
            TenantContext or None
        """
        if not ctx or not ctx.request_context or not ctx.request_context.request:
            return None
        
        request = ctx.request_context.request
        
        # Check X-Tenant-ID header first (direct context forwarding)
        tenant_id = request.headers.get("x-tenant-id")
        if tenant_id:
            return TenantContext(
                tenant_id=tenant_id.strip(),
                namespace=f"{tenant_id.lower().replace('-', '_')}_mcp",
            )
        
        # Fallback: parse tenant from Authorization Bearer token
        # (would need token decoding, typically done by auth middleware)
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            logger.debug(f"Would extract tenant from token (length: {len(token)})")
            # Token decoding typically handled by auth provider
        
        return None
    
    def _extract_tenant_id(self, token_payload: dict[str, Any]) -> str | None:
        """Extract tenant ID from token payload."""
        # Try primary claim
        value = token_payload.get(self.extract_claim)
        if value:
            if isinstance(value, list):
                return str(value[0]) if value else None
            return str(value)
        
        # Try fallback claims
        for claim in self.fallback_claims:
            value = token_payload.get(claim)
            if value:
                if isinstance(value, list):
                    return str(value[0]) if value else None
                return str(value)
        
        return None


class TenantHeaderForwarder:
    """Forward tenant context to downstream MCPs via HTTP headers."""
    
    def __init__(self, header_name: str = "X-Tenant-ID"):
        """Initialize forwarder.
        
        Args:
            header_name: HTTP header for tenant context
        """
        self.header_name = header_name
    
    def add_tenant_headers(
        self,
        headers: dict[str, str],
        tenant_context: TenantContext | None,
    ) -> dict[str, str]:
        """Add tenant-related headers to outgoing request.
        
        Args:
            headers: Existing headers dict
            tenant_context: Tenant context or None
        
        Returns:
            Updated headers with tenant info
        """
        if not tenant_context:
            return headers
        
        updated = dict(headers)
        updated[self.header_name] = tenant_context.tenant_id
        
        # Optional: Add org ID if available
        if tenant_context.org_id:
            updated["X-Org-ID"] = tenant_context.org_id
        
        # Optional: Add namespace for routing
        if tenant_context.namespace:
            updated["X-MCP-Namespace"] = tenant_context.namespace
        
        # Optional: Forward roles for authorization
        if tenant_context.roles:
            updated["X-User-Roles"] = ",".join(tenant_context.roles)
        
        # Optional: Forward scopes for fine-grained authz
        if tenant_context.scopes:
            updated["X-User-Scopes"] = ",".join(tenant_context.scopes)
        
        return updated


class TenantScopeValidator:
    """Validate tenant-scoped OAuth scopes."""
    
    def __init__(self, scope_format: str = "{tenant}:{scope}"):
        """Initialize validator.
        
        Args:
            scope_format: Format for tenant-scoped scope (e.g., "acme:tools:read")
        """
        self.scope_format = scope_format
    
    def validate_scopes(
        self,
        token_scopes: list[str],
        tenant_id: str,
        required_scope: str,
    ) -> bool:
        """Validate that token includes tenant-scoped permission.
        
        Args:
            token_scopes: Scopes from token
            tenant_id: Tenant ID
            required_scope: Required scope (e.g., "tools:read")
        
        Returns:
            True if valid
        """
        # Build expected tenant-scoped scope
        tenant_scoped = self.scope_format.format(tenant=tenant_id, scope=required_scope)
        
        # Check for tenant-scoped match
        if tenant_scoped in token_scopes:
            return True
        
        # Check for global scope (admin override)
        if required_scope in token_scopes:
            logger.debug(f"Using global scope '{required_scope}' (admin override)")
            return True
        
        # Check for wildcard scope
        wildcard = self.scope_format.format(tenant=tenant_id, scope="*")
        if wildcard in token_scopes:
            logger.debug(f"Using wildcard scope '{wildcard}'")
            return True
        
        logger.warning(f"Scope validation failed: {required_scope} not found for tenant {tenant_id}")
        return False
    
    def build_scoped_scope(self, base_scope: str, tenant_id: str) -> str:
        """Build tenant-scoped scope string.
        
        Args:
            base_scope: Base scope (e.g., "tools:read")
            tenant_id: Tenant ID
        
        Returns:
            Tenant-scoped scope (e.g., "acme:tools:read")
        """
        return self.scope_format.format(tenant=tenant_id, scope=base_scope)
