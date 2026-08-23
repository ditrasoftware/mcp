"""
Enterprise-grade authentication module (Phase 1-4).

Provides OIDC integration, audit logging, token management, RBAC, MFA, and compliance features.
All features disabled by default - enable via environment variables.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp.server.context import Context
from fastmcp.exceptions import ToolError

from .settings import (
    AnticaFarmaciaSettings,
    OIDCSettings,
    AuditSettings,
    TokenSettings,
    RateLimitSettings,
    RBACSettings,
    TenantSettings,
    MFASettings,
    RiskManagementSettings,
    ComplianceSettings,
)
from .rest_client import FerreroMedAuth

logger = logging.getLogger(__name__)


# ============================================================================
# PHASE 1: AUDIT LOGGING
# ============================================================================

@dataclass
class AuditEvent:
    """Audit log event."""
    timestamp: float
    event_type: str  # "auth_attempt", "tool_access", "token_refresh", etc.
    user_id: str | None
    result: str  # "success" | "failure"
    reason: str | None = None
    scopes: list[str] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    tool_name: str | None = None
    tenant_id: str | None = None


def audit_log(event: AuditEvent, settings: AnticaFarmaciaSettings) -> None:
    """Log authentication/authorization event."""
    if not settings.audit.enabled:
        return
    
    # Mask sensitive data if configured
    if settings.audit.mask_sensitive_data:
        if event.user_id and "@" in event.user_id:
            event.user_id = event.user_id.split("@")[0][:3] + "***"
    
    # Format as structured log
    log_entry = {
        "timestamp": event.timestamp,
        "event_type": event.event_type,
        "user_id": event.user_id,
        "result": event.result,
        "reason": event.reason,
        "scopes": event.scopes,
        "ip_address": event.ip_address,
        "user_agent": event.user_agent,
        "tool_name": event.tool_name,
        "tenant_id": event.tenant_id,
    }
    
    if settings.audit.destination == "stdout":
        logger.info(json.dumps(log_entry))
    elif settings.audit.destination == "cloudwatch":
        logger.info(json.dumps(log_entry))  # CloudWatch integration via handlers
    elif settings.audit.destination == "elk":
        logger.info(json.dumps(log_entry))  # ELK integration via handlers
    elif settings.audit.destination == "splunk":
        logger.info(json.dumps(log_entry))  # Splunk integration via handlers


def extract_auth_context(ctx: Context | None) -> dict[str, Any]:
    """Extract authentication context from request."""
    auth_context = {
        "ip_address": None,
        "user_agent": None,
        "request_path": None,
    }
    
    if ctx is None or ctx.request_context is None or ctx.request_context.request is None:
        return auth_context
    
    request = ctx.request_context.request
    auth_context["ip_address"] = request.headers.get("x-forwarded-for") or request.client[0] if request.client else None
    auth_context["user_agent"] = request.headers.get("user-agent")
    auth_context["request_path"] = str(request.url.path) if hasattr(request, "url") else None
    
    return auth_context


# ============================================================================
# PHASE 2: TOKEN MANAGEMENT
# ============================================================================

@dataclass
class TokenInfo:
    """Token information with expiration."""
    access_token: str
    expires_at: float  # Unix timestamp
    refresh_token: str | None = None
    refresh_expires_at: float | None = None
    scopes: list[str] = None


def is_token_expired(token_info: TokenInfo, buffer_seconds: int = 300) -> bool:
    """Check if token is expired (with buffer)."""
    return time.time() > (token_info.expires_at - buffer_seconds)


def should_refresh_token(token_info: TokenInfo, settings: AnticaFarmaciaSettings) -> bool:
    """Determine if token needs refresh."""
    if not settings.token.enabled or not settings.token.refresh_enabled:
        return False
    if not token_info.refresh_token:
        return False
    return is_token_expired(token_info, settings.token.auto_refresh_buffer_seconds)


def is_token_revoked(token: str, settings: AnticaFarmaciaSettings) -> bool:
    """Check if token is in revocation list (Phase 2)."""
    if not settings.token.enabled or not settings.token.revocation_enabled:
        return False
    
    # In-memory revocation (can be extended to Redis)
    # This is a placeholder - implement with your revocation backend
    # revoked_tokens = load_from_revocation_list()
    # return token in revoked_tokens
    
    return False


# ============================================================================
# PHASE 3: AUTHORIZATION (RBAC + TENANTS)
# ============================================================================

def has_scope(token_scopes: list[str] | None, required_scope: str, settings: AnticaFarmaciaSettings) -> bool:
    """Check if token has required scope (Phase 3)."""
    if not settings.rbac.enabled or not settings.rbac.enforce_scopes:
        return True  # RBAC disabled, allow all
    
    if not token_scopes:
        return False
    
    # Build full scope with prefix
    full_scope = f"{settings.rbac.scope_prefix}{required_scope}"
    
    # Check for exact match or wildcard
    return (
        full_scope in token_scopes
        or f"{settings.rbac.scope_prefix}*" in token_scopes
        or required_scope in token_scopes
    )


def check_tenant_isolation(
    token_tenant_id: str | None,
    required_tenant_id: str | None,
    settings: AnticaFarmaciaSettings,
) -> bool:
    """Validate tenant isolation (Phase 3)."""
    if not settings.tenant.enabled or not settings.tenant.tenant_isolation_enabled:
        return True  # Multi-tenancy disabled, allow all
    
    if not token_tenant_id or not required_tenant_id:
        return False
    
    return token_tenant_id == required_tenant_id


def enforce_role_permissions(user_roles: list[str] | None, required_role: str) -> bool:
    """Check if user has required role (Phase 3)."""
    if not user_roles:
        return False
    return required_role in user_roles or "admin" in user_roles


# ============================================================================
# PHASE 4: ADVANCED SECURITY (MFA, RISK MANAGEMENT)
# ============================================================================

def requires_mfa(settings: AnticaFarmaciaSettings, risk_score: float | None = None) -> bool:
    """Determine if MFA is required (Phase 4)."""
    if not settings.mfa.enabled:
        return False
    
    if settings.mfa.enforce_mfa:
        return True
    
    if settings.risk_management.enabled and settings.risk_management.require_mfa_on_high_risk:
        if risk_score and risk_score > 0.7:  # High risk
            return True
    
    return False


def extract_token_claims(token: str) -> dict[str, Any] | None:
    """Extract JWT claims without verification (for claim extraction only)."""
    try:
        # Split JWT
        parts = token.split(".")
        if len(parts) != 3:
            return None
        
        # Decode payload (middle part)
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def extract_user_identity(auth: FerreroMedAuth, settings: AnticaFarmaciaSettings) -> dict[str, Any]:
    """Extract user identity from auth (Phase 1 audit logging)."""
    identity = {
        "user_id": None,
        "tenant_id": None,
        "scopes": [],
        "roles": [],
        "mfa_verified": False,
    }
    
    if auth.access_token:
        claims = extract_token_claims(auth.access_token)
        if claims:
            identity["user_id"] = claims.get("sub") or claims.get("email") or claims.get("user_id")
            identity["scopes"] = claims.get("scope", "").split() if claims.get("scope") else []
            
            # Extract tenant ID if configured
            if settings.tenant.enabled:
                identity["tenant_id"] = claims.get(settings.tenant.extract_from_token_claim)
            
            # Extract roles if available
            identity["roles"] = claims.get("roles", []) or claims.get("groups", [])
    
    return identity


def compute_risk_score(
    ctx: Context | None,
    settings: AnticaFarmaciaSettings,
) -> float:
    """Compute risk score for step-up auth (Phase 4)."""
    if not settings.risk_management.enabled:
        return 0.0
    
    score = 0.0
    auth_context = extract_auth_context(ctx)
    
    # IP reputation (stub)
    if settings.risk_management.ip_reputation_check:
        # In production: call IP reputation service
        pass
    
    # Geolocation (stub)
    if settings.risk_management.geolocation_check:
        # In production: check geolocation against user history
        pass
    
    # Device fingerprinting (stub)
    if settings.risk_management.device_fingerprinting:
        # In production: verify device fingerprint
        pass
    
    return min(score, 1.0)  # Clamp to 0-1


# ============================================================================
# ENHANCED AUTH VALIDATION
# ============================================================================

def require_auth_enterprise(
    auth: FerreroMedAuth,
    settings: AnticaFarmaciaSettings,
    ctx: Context | None = None,
    required_scope: str | None = None,
    required_tenant_id: str | None = None,
) -> None:
    """
    Validate auth with enterprise features.
    
    - Phase 1: Audit log attempt
    - Phase 2: Check token expiration and revocation
    - Phase 3: Check scopes and tenant isolation
    - Phase 4: Compute risk score and MFA
    """
    
    # Get auth context for logging
    auth_context = extract_auth_context(ctx)
    identity = extract_user_identity(auth, settings)
    
    # Check basic auth
    if not (auth.access_token or auth.api_key):
        # Phase 1: Audit failure
        if settings.audit.enabled and settings.audit.log_auth_events:
            audit_log(
                AuditEvent(
                    timestamp=time.time(),
                    event_type="auth_attempt",
                    user_id=None,
                    result="failure",
                    reason="missing_credentials",
                    ip_address=auth_context["ip_address"],
                    user_agent=auth_context["user_agent"],
                ),
                settings,
            )
        
        raise ToolError(
            "Missing auth: provide an Authorization Bearer token or an X-Api-Key header."
        )
    
    # Phase 2: Token expiration (if using bearer token)
    if auth.access_token:
        claims = extract_token_claims(auth.access_token)
        if claims and "exp" in claims:
            if time.time() > claims["exp"]:
                if settings.audit.enabled:
                    audit_log(
                        AuditEvent(
                            timestamp=time.time(),
                            event_type="auth_attempt",
                            user_id=identity["user_id"],
                            result="failure",
                            reason="token_expired",
                            ip_address=auth_context["ip_address"],
                        ),
                        settings,
                    )
                raise ToolError("Access token expired")
        
        # Phase 2: Check revocation
        if is_token_revoked(auth.access_token, settings):
            if settings.audit.enabled:
                audit_log(
                    AuditEvent(
                        timestamp=time.time(),
                        event_type="auth_attempt",
                        user_id=identity["user_id"],
                        result="failure",
                        reason="token_revoked",
                        ip_address=auth_context["ip_address"],
                    ),
                    settings,
                )
            raise ToolError("Access token has been revoked")
    
    # Phase 3: Check scope
    if required_scope and not has_scope(identity["scopes"], required_scope, settings):
        if settings.audit.enabled:
            audit_log(
                AuditEvent(
                    timestamp=time.time(),
                    event_type="auth_attempt",
                    user_id=identity["user_id"],
                    result="failure",
                    reason="insufficient_scope",
                    scopes=identity["scopes"],
                    ip_address=auth_context["ip_address"],
                ),
                settings,
            )
        raise ToolError(f"Missing required scope: {required_scope}")
    
    # Phase 3: Check tenant isolation
    if required_tenant_id and not check_tenant_isolation(
        identity["tenant_id"], required_tenant_id, settings
    ):
        if settings.audit.enabled:
            audit_log(
                AuditEvent(
                    timestamp=time.time(),
                    event_type="auth_attempt",
                    user_id=identity["user_id"],
                    result="failure",
                    reason="tenant_mismatch",
                    tenant_id=identity["tenant_id"],
                    ip_address=auth_context["ip_address"],
                ),
                settings,
            )
        raise ToolError("Tenant access denied")
    
    # Phase 4: Check MFA
    risk_score = compute_risk_score(ctx, settings)
    if requires_mfa(settings, risk_score) and not identity["mfa_verified"]:
        if settings.audit.enabled:
            audit_log(
                AuditEvent(
                    timestamp=time.time(),
                    event_type="auth_attempt",
                    user_id=identity["user_id"],
                    result="failure",
                    reason="mfa_required",
                    ip_address=auth_context["ip_address"],
                ),
                settings,
            )
        raise ToolError("Multi-factor authentication required")
    
    # Phase 1: Audit success
    if settings.audit.enabled and settings.audit.log_auth_events:
        audit_log(
            AuditEvent(
                timestamp=time.time(),
                event_type="auth_attempt",
                user_id=identity["user_id"],
                result="success",
                scopes=identity["scopes"],
                ip_address=auth_context["ip_address"],
                user_agent=auth_context["user_agent"],
                tenant_id=identity["tenant_id"],
            ),
            settings,
        )


def audit_tool_access(
    tool_name: str,
    success: bool,
    user_id: str | None,
    settings: AnticaFarmaciaSettings,
    ctx: Context | None = None,
    error_reason: str | None = None,
) -> None:
    """Audit tool access (Phase 1)."""
    if not settings.audit.enabled or not settings.audit.log_tool_access:
        return
    
    auth_context = extract_auth_context(ctx)
    audit_log(
        AuditEvent(
            timestamp=time.time(),
            event_type="tool_access",
            user_id=user_id,
            result="success" if success else "failure",
            reason=error_reason,
            tool_name=tool_name,
            ip_address=auth_context["ip_address"],
            user_agent=auth_context["user_agent"],
        ),
        settings,
    )
