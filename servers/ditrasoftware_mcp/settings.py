from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteBackendSettings:
    name: str
    namespace: str
    type: str
    url: str
    init_timeout_ms: int = 20000
    timeout_ms: int = 60000
    server_instructions: bool = True
    enabled: bool = True


@dataclass(frozen=True)
class GatewaySettings:
    mode: str = "hybrid"
    route_policy: str = "local_preferred"
    mount_on_startup: bool = True
    allow_direct_calls: bool = True
    direct_result_strategy: str = "passthrough"
    tool_route_overrides: tuple[tuple[str, str], ...] = ()
    remotes: tuple[RemoteBackendSettings, ...] = ()


# PHASE 1: Foundation (OIDC + Audit Logging)
@dataclass(frozen=True)
class OIDCSettings:
    """OIDC/OAuth2 provider configuration (Phase 1)."""
    enabled: bool = False
    mode: str = "oidc_proxy"  # "oidc_proxy" | "supabase"
    config_url: str | None = None  # e.g., https://ditra.auth0.com/.well-known/openid-configuration
    client_id: str | None = None
    client_secret: str | None = None
    required_scopes: tuple[str, ...] = ("openid", "profile", "email")
    allow_api_key_fallback: bool = True
    verify_id_token: bool = True
    mcp_base_url: str | None = None  # e.g., https://ditrasoftware.ditra.io
    token_endpoint_auth_method: str = "client_secret_basic"


@dataclass(frozen=True)
class AuditSettings:
    """Audit logging configuration (Phase 1)."""
    enabled: bool = False
    destination: str = "stdout"  # "stdout" | "cloudwatch" | "elk" | "splunk"
    cloudwatch_log_group: str | None = None
    cloudwatch_log_stream: str | None = None
    elk_endpoint: str | None = None  # e.g., https://elk.example.com
    splunk_endpoint: str | None = None  # e.g., https://splunk.example.com:8088
    splunk_token: str | None = None
    log_auth_events: bool = True
    log_tool_access: bool = True
    log_api_calls: bool = False
    mask_sensitive_data: bool = True
    retention_days: int = 2555  # 7 years for compliance


# PHASE 2: Token Management + Rate Limiting
@dataclass(frozen=True)
class TokenSettings:
    """Token lifecycle configuration (Phase 2)."""
    enabled: bool = False
    access_token_ttl_seconds: int = 3600  # 1 hour
    refresh_token_ttl_seconds: int = 2592000  # 30 days
    auto_refresh_buffer_seconds: int = 300  # Refresh 5 min before expiry
    refresh_enabled: bool = False
    revocation_enabled: bool = False
    revocation_check_interval_seconds: int = 60
    revocation_backend: str = "memory"  # "memory" | "redis" | "vault"
    redis_url: str | None = None  # e.g., redis://localhost:6379


@dataclass(frozen=True)
class RateLimitSettings:
    """Rate limiting configuration (Phase 2)."""
    enabled: bool = False
    per_user_limit: int = 1000  # per hour
    per_api_key_limit: int = 10000  # per hour
    per_ip_limit: int = 5000  # per hour
    per_tenant_limit: int = 50000  # per hour
    token_endpoint_limit: int = 100  # per minute
    auth_endpoint_limit: int = 50  # per minute
    storage_backend: str = "memory"  # "memory" | "redis"


# PHASE 3: Authorization (RBAC + Multi-tenancy)
@dataclass(frozen=True)
class RBACSettings:
    """Role-based access control configuration (Phase 3)."""
    enabled: bool = False
    enforce_scopes: bool = False  # Require OAuth scopes for tools
    scope_prefix: str = "ditrasoftware:"  # e.g., ditrasoftware:inventory:read
    roles_enabled: bool = False  # Use Auth0 groups as roles
    resource_permissions_enabled: bool = False  # Per-resource RBAC


@dataclass(frozen=True)
class TenantSettings:
    """Multi-tenancy configuration (Phase 3)."""
    enabled: bool = False
    tenant_isolation_enabled: bool = False
    extract_from_token_claim: str = "tenant_id"  # Which JWT claim contains tenant
    allow_cross_tenant_queries: bool = False
    scim_provisioning_enabled: bool = False


# PHASE 4: Compliance + MFA + Risk Management
@dataclass(frozen=True)
class MFASettings:
    """Multi-factor authentication configuration (Phase 4)."""
    enabled: bool = False
    enforce_mfa: bool = False
    supported_methods: tuple[str, ...] = ("totp", "sms", "email", "webauthn")
    totp_issuer: str = "DitraSoftware MCP"
    backup_codes_enabled: bool = True
    grace_period_days: int = 7  # Grace period to enroll MFA


@dataclass(frozen=True)
class RiskManagementSettings:
    """Risk-based authentication configuration (Phase 4)."""
    enabled: bool = False
    ip_reputation_check: bool = False
    geolocation_check: bool = False
    device_fingerprinting: bool = False
    anomaly_detection: bool = False
    step_up_auth_on_risk: bool = False
    require_mfa_on_high_risk: bool = False
    max_concurrent_sessions: int | None = None
    session_timeout_minutes: int = 60


@dataclass(frozen=True)
class ComplianceSettings:
    """Compliance framework configuration (Phase 4)."""
    enabled: bool = False
    frameworks: tuple[str, ...] = ()  # "gdpr", "hipaa", "pci-dss", "soc2"
    gdpr_enabled: bool = False
    gdpr_data_residency: str | None = None  # "eu", "us", "default"
    hipaa_enabled: bool = False
    hipaa_encryption_enabled: bool = True
    pci_dss_enabled: bool = False
    soc2_enabled: bool = False
    audit_retention_years: int = 7
    right_to_be_forgotten_enabled: bool = False


@dataclass(frozen=True)
class DitraSoftwareSettings:
    api_base_url: str
    timeout_seconds: float = 30.0
    verify_ssl: bool = True
    default_api_key: str | None = None
    cache_ttl: int | None = None
    cache_scope: str = "private"
    list_page_size: int | None = None
    mask_error_details: bool = False
    gateway: GatewaySettings = GatewaySettings()
    # Phase 1: Foundation
    oidc: OIDCSettings = OIDCSettings()
    audit: AuditSettings = AuditSettings()
    # Phase 2: Token Management
    token: TokenSettings = TokenSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()
    # Phase 3: Authorization
    rbac: RBACSettings = RBACSettings()
    tenant: TenantSettings = TenantSettings()
    # Phase 4: Compliance
    mfa: MFASettings = MFASettings()
    risk_management: RiskManagementSettings = RiskManagementSettings()
    compliance: ComplianceSettings = ComplianceSettings()


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _coerce_positive_int(value: int | str | None) -> int | None:
    """Convert value to a positive integer, or None if not positive."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    s = str(value).strip()
    if not s:
        return None
    try:
        n = int(float(s))
    except ValueError:
        return None
    return n if n > 0 else None



def _parse_remote_backends_from_env() -> tuple[RemoteBackendSettings, ...] | None:
    raw = (os.getenv("DITRASOFTWARE_GATEWAY_REMOTES_JSON") or "").strip()
    if not raw:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, list):
        return None

    remotes: list[RemoteBackendSettings] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or "").strip()
        namespace = str(item.get("namespace") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not namespace or not url:
            continue

        init_timeout_ms = int(item.get("initTimeout", 20000) or 20000)
        timeout_ms = int(item.get("timeout", 60000) or 60000)
        server_instructions = bool(item.get("serverInstructions", True))
        enabled = bool(item.get("enabled", True))
        remote_type = str(item.get("type") or "streamable-http").strip() or "streamable-http"

        remotes.append(
            RemoteBackendSettings(
                name=name,
                namespace=namespace,
                type=remote_type,
                url=url,
                init_timeout_ms=init_timeout_ms,
                timeout_ms=timeout_ms,
                server_instructions=server_instructions,
                enabled=enabled,
            )
        )

    return tuple(remotes)


def _parse_tool_route_overrides_from_env() -> tuple[tuple[str, str], ...]:
    raw = (os.getenv("DITRASOFTWARE_GATEWAY_TOOL_ROUTE_OVERRIDES_JSON") or "").strip()
    if not raw:
        return ()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ()

    if not isinstance(data, dict):
        return ()

    allowed = {"local", "remote"}
    overrides: list[tuple[str, str]] = []
    for tool_name, route in data.items():
        key = str(tool_name or "").strip()
        value = str(route or "").strip().lower()
        if not key or value not in allowed:
            continue
        overrides.append((key, value))

    return tuple(overrides)


def _default_toolbox_remotes() -> tuple[RemoteBackendSettings, ...]:
    enabled = _get_bool_env("DITRASOFTWARE_GATEWAY_ENABLE_TOOLBOX", True)
    host = (os.getenv("DITRASOFTWARE_GATEWAY_TOOLBOX_HOST") or "toolbox").strip() or "toolbox"
    port = _get_int_env("DITRASOFTWARE_GATEWAY_TOOLBOX_PORT", 5000)
    init_timeout_ms = _get_int_env("DITRASOFTWARE_GATEWAY_TOOLBOX_INIT_TIMEOUT_MS", 20000)
    timeout_ms = _get_int_env("DITRASOFTWARE_GATEWAY_TOOLBOX_TIMEOUT_MS", 60000)
    server_instructions = _get_bool_env("DITRASOFTWARE_GATEWAY_TOOLBOX_SERVER_INSTRUCTIONS", True)

    return (
        RemoteBackendSettings(
            name="toolbox-mssql",
            namespace="toolbox_mssql",
            type="streamable-http",
            url=f"http://{host}:{port}/mcp/mssql",
            init_timeout_ms=init_timeout_ms,
            timeout_ms=timeout_ms,
            server_instructions=server_instructions,
            enabled=enabled,
        ),
        RemoteBackendSettings(
            name="toolbox-mysql",
            namespace="toolbox_mysql",
            type="streamable-http",
            url=f"http://{host}:{port}/mcp/mysql",
            init_timeout_ms=init_timeout_ms,
            timeout_ms=timeout_ms,
            server_instructions=server_instructions,
            enabled=enabled,
        ),
    )


def _build_gateway_settings() -> GatewaySettings:
    mode = (os.getenv("DITRASOFTWARE_GATEWAY_MODE") or "hybrid").strip().lower() or "hybrid"
    route_policy = (
        (os.getenv("DITRASOFTWARE_GATEWAY_ROUTE_POLICY") or "local_preferred").strip().lower()
        or "local_preferred"
    )
    mount_on_startup = _get_bool_env("DITRASOFTWARE_GATEWAY_MOUNT_ON_STARTUP", True)
    allow_direct_calls = _get_bool_env("DITRASOFTWARE_GATEWAY_ALLOW_DIRECT_CALLS", True)
    direct_result_strategy = (
        (os.getenv("DITRASOFTWARE_GATEWAY_DIRECT_RESULT_STRATEGY") or "passthrough")
        .strip()
        .lower()
    ) or "passthrough"
    if direct_result_strategy not in {"passthrough", "normalized"}:
        direct_result_strategy = "passthrough"
    tool_route_overrides = _parse_tool_route_overrides_from_env()

    remotes = _parse_remote_backends_from_env() or _default_toolbox_remotes()

    # Keep only enabled remotes; explicit per-remote disabling is supported.
    filtered = tuple(r for r in remotes if r.enabled)

    return GatewaySettings(
        mode=mode,
        route_policy=route_policy,
        mount_on_startup=mount_on_startup,
        allow_direct_calls=allow_direct_calls,
        direct_result_strategy=direct_result_strategy,
        tool_route_overrides=tool_route_overrides,
        remotes=filtered,
    )


# Enterprise Authentication: Phase 1-4 Builders (disabled by default)

def _build_oidc_settings() -> OIDCSettings:
    """Build OIDC configuration (Phase 1)."""
    enabled = _get_bool_env("DITRASOFTWARE_AUTH_OIDC_ENABLED", False)
    mode = (os.getenv("DITRASOFTWARE_AUTH_OIDC_MODE") or "oidc_proxy").strip().lower()
    config_url = (os.getenv("DITRASOFTWARE_AUTH_OIDC_CONFIG_URL") or "").strip() or None
    client_id = (os.getenv("DITRASOFTWARE_AUTH_OIDC_CLIENT_ID") or "").strip() or None
    client_secret = (os.getenv("DITRASOFTWARE_AUTH_OIDC_CLIENT_SECRET") or "").strip() or None
    mcp_base_url = (os.getenv("DITRASOFTWARE_AUTH_OIDC_MCP_BASE_URL") or "").strip() or None
    
    required_scopes_raw = (os.getenv("DITRASOFTWARE_AUTH_OIDC_REQUIRED_SCOPES") or "openid profile email").strip()
    required_scopes = tuple(s.strip() for s in required_scopes_raw.split(",") if s.strip())
    
    allow_api_key_fallback = _get_bool_env("DITRASOFTWARE_AUTH_OIDC_ALLOW_API_KEY_FALLBACK", True)
    verify_id_token = _get_bool_env("DITRASOFTWARE_AUTH_OIDC_VERIFY_ID_TOKEN", True)
    token_endpoint_auth_method = (os.getenv("DITRASOFTWARE_AUTH_OIDC_TOKEN_ENDPOINT_AUTH_METHOD") or "client_secret_basic").strip().lower()
    
    return OIDCSettings(
        enabled=enabled,
        mode=mode,
        config_url=config_url,
        client_id=client_id,
        client_secret=client_secret,
        mcp_base_url=mcp_base_url,
        required_scopes=required_scopes,
        allow_api_key_fallback=allow_api_key_fallback,
        verify_id_token=verify_id_token,
        token_endpoint_auth_method=token_endpoint_auth_method,
    )


def _build_audit_settings() -> AuditSettings:
    """Build audit logging configuration (Phase 1)."""
    enabled = _get_bool_env("DITRASOFTWARE_AUDIT_ENABLED", False)
    destination = (os.getenv("DITRASOFTWARE_AUDIT_DESTINATION") or "stdout").strip().lower()
    cloudwatch_log_group = (os.getenv("DITRASOFTWARE_AUDIT_CLOUDWATCH_LOG_GROUP") or "").strip() or None
    cloudwatch_log_stream = (os.getenv("DITRASOFTWARE_AUDIT_CLOUDWATCH_LOG_STREAM") or "").strip() or None
    elk_endpoint = (os.getenv("DITRASOFTWARE_AUDIT_ELK_ENDPOINT") or "").strip() or None
    splunk_endpoint = (os.getenv("DITRASOFTWARE_AUDIT_SPLUNK_ENDPOINT") or "").strip() or None
    splunk_token = (os.getenv("DITRASOFTWARE_AUDIT_SPLUNK_TOKEN") or "").strip() or None
    log_auth_events = _get_bool_env("DITRASOFTWARE_AUDIT_LOG_AUTH_EVENTS", True)
    log_tool_access = _get_bool_env("DITRASOFTWARE_AUDIT_LOG_TOOL_ACCESS", True)
    log_api_calls = _get_bool_env("DITRASOFTWARE_AUDIT_LOG_API_CALLS", False)
    mask_sensitive_data = _get_bool_env("DITRASOFTWARE_AUDIT_MASK_SENSITIVE_DATA", True)
    retention_days = _get_int_env("DITRASOFTWARE_AUDIT_RETENTION_DAYS", 2555)
    
    return AuditSettings(
        enabled=enabled,
        destination=destination,
        cloudwatch_log_group=cloudwatch_log_group,
        cloudwatch_log_stream=cloudwatch_log_stream,
        elk_endpoint=elk_endpoint,
        splunk_endpoint=splunk_endpoint,
        splunk_token=splunk_token,
        log_auth_events=log_auth_events,
        log_tool_access=log_tool_access,
        log_api_calls=log_api_calls,
        mask_sensitive_data=mask_sensitive_data,
        retention_days=retention_days,
    )


def _build_token_settings() -> TokenSettings:
    """Build token management configuration (Phase 2)."""
    enabled = _get_bool_env("DITRASOFTWARE_AUTH_TOKEN_ENABLED", False)
    access_token_ttl = _get_int_env("DITRASOFTWARE_AUTH_TOKEN_ACCESS_TTL_SECONDS", 3600)
    refresh_token_ttl = _get_int_env("DITRASOFTWARE_AUTH_TOKEN_REFRESH_TTL_SECONDS", 2592000)
    auto_refresh_buffer = _get_int_env("DITRASOFTWARE_AUTH_TOKEN_AUTO_REFRESH_BUFFER_SECONDS", 300)
    refresh_enabled = _get_bool_env("DITRASOFTWARE_AUTH_TOKEN_REFRESH_ENABLED", False)
    revocation_enabled = _get_bool_env("DITRASOFTWARE_AUTH_TOKEN_REVOCATION_ENABLED", False)
    revocation_check_interval = _get_int_env("DITRASOFTWARE_AUTH_TOKEN_REVOCATION_CHECK_INTERVAL_SECONDS", 60)
    revocation_backend = (os.getenv("DITRASOFTWARE_AUTH_TOKEN_REVOCATION_BACKEND") or "memory").strip().lower()
    redis_url = (os.getenv("DITRASOFTWARE_AUTH_TOKEN_REDIS_URL") or "").strip() or None
    
    return TokenSettings(
        enabled=enabled,
        access_token_ttl_seconds=access_token_ttl,
        refresh_token_ttl_seconds=refresh_token_ttl,
        auto_refresh_buffer_seconds=auto_refresh_buffer,
        refresh_enabled=refresh_enabled,
        revocation_enabled=revocation_enabled,
        revocation_check_interval_seconds=revocation_check_interval,
        revocation_backend=revocation_backend,
        redis_url=redis_url,
    )


def _build_rate_limit_settings() -> RateLimitSettings:
    """Build rate limiting configuration (Phase 2)."""
    enabled = _get_bool_env("DITRASOFTWARE_RATE_LIMIT_ENABLED", False)
    per_user = _get_int_env("DITRASOFTWARE_RATE_LIMIT_PER_USER", 1000)
    per_api_key = _get_int_env("DITRASOFTWARE_RATE_LIMIT_PER_API_KEY", 10000)
    per_ip = _get_int_env("DITRASOFTWARE_RATE_LIMIT_PER_IP", 5000)
    per_tenant = _get_int_env("DITRASOFTWARE_RATE_LIMIT_PER_TENANT", 50000)
    token_endpoint_limit = _get_int_env("DITRASOFTWARE_RATE_LIMIT_TOKEN_ENDPOINT", 100)
    auth_endpoint_limit = _get_int_env("DITRASOFTWARE_RATE_LIMIT_AUTH_ENDPOINT", 50)
    storage_backend = (os.getenv("DITRASOFTWARE_RATE_LIMIT_STORAGE_BACKEND") or "memory").strip().lower()
    
    return RateLimitSettings(
        enabled=enabled,
        per_user_limit=per_user,
        per_api_key_limit=per_api_key,
        per_ip_limit=per_ip,
        per_tenant_limit=per_tenant,
        token_endpoint_limit=token_endpoint_limit,
        auth_endpoint_limit=auth_endpoint_limit,
        storage_backend=storage_backend,
    )


def _build_rbac_settings() -> RBACSettings:
    """Build RBAC configuration (Phase 3)."""
    enabled = _get_bool_env("DITRASOFTWARE_RBAC_ENABLED", False)
    enforce_scopes = _get_bool_env("DITRASOFTWARE_RBAC_ENFORCE_SCOPES", False)
    scope_prefix = (os.getenv("DITRASOFTWARE_RBAC_SCOPE_PREFIX") or "ditrasoftware:").strip()
    roles_enabled = _get_bool_env("DITRASOFTWARE_RBAC_ROLES_ENABLED", False)
    resource_permissions_enabled = _get_bool_env("DITRASOFTWARE_RBAC_RESOURCE_PERMISSIONS_ENABLED", False)
    
    return RBACSettings(
        enabled=enabled,
        enforce_scopes=enforce_scopes,
        scope_prefix=scope_prefix,
        roles_enabled=roles_enabled,
        resource_permissions_enabled=resource_permissions_enabled,
    )


def _build_tenant_settings() -> TenantSettings:
    """Build multi-tenancy configuration (Phase 3)."""
    enabled = _get_bool_env("DITRASOFTWARE_TENANT_ENABLED", False)
    tenant_isolation_enabled = _get_bool_env("DITRASOFTWARE_TENANT_ISOLATION_ENABLED", False)
    extract_from_token_claim = (os.getenv("DITRASOFTWARE_TENANT_EXTRACT_FROM_TOKEN_CLAIM") or "tenant_id").strip()
    allow_cross_tenant_queries = _get_bool_env("DITRASOFTWARE_TENANT_ALLOW_CROSS_TENANT_QUERIES", False)
    scim_provisioning_enabled = _get_bool_env("DITRASOFTWARE_TENANT_SCIM_PROVISIONING_ENABLED", False)
    
    return TenantSettings(
        enabled=enabled,
        tenant_isolation_enabled=tenant_isolation_enabled,
        extract_from_token_claim=extract_from_token_claim,
        allow_cross_tenant_queries=allow_cross_tenant_queries,
        scim_provisioning_enabled=scim_provisioning_enabled,
    )


def _build_mfa_settings() -> MFASettings:
    """Build MFA configuration (Phase 4)."""
    enabled = _get_bool_env("DITRASOFTWARE_MFA_ENABLED", False)
    enforce_mfa = _get_bool_env("DITRASOFTWARE_MFA_ENFORCE_MFA", False)
    supported_methods_raw = (os.getenv("DITRASOFTWARE_MFA_SUPPORTED_METHODS") or "totp,sms,email,webauthn").strip()
    supported_methods = tuple(m.strip() for m in supported_methods_raw.split(",") if m.strip())
    totp_issuer = (os.getenv("DITRASOFTWARE_MFA_TOTP_ISSUER") or "DitraSoftware MCP").strip()
    backup_codes_enabled = _get_bool_env("DITRASOFTWARE_MFA_BACKUP_CODES_ENABLED", True)
    grace_period_days = _get_int_env("DITRASOFTWARE_MFA_GRACE_PERIOD_DAYS", 7)
    
    return MFASettings(
        enabled=enabled,
        enforce_mfa=enforce_mfa,
        supported_methods=supported_methods,
        totp_issuer=totp_issuer,
        backup_codes_enabled=backup_codes_enabled,
        grace_period_days=grace_period_days,
    )


def _build_risk_management_settings() -> RiskManagementSettings:
    """Build risk management configuration (Phase 4)."""
    enabled = _get_bool_env("DITRASOFTWARE_RISK_MANAGEMENT_ENABLED", False)
    ip_reputation_check = _get_bool_env("DITRASOFTWARE_RISK_MANAGEMENT_IP_REPUTATION_CHECK", False)
    geolocation_check = _get_bool_env("DITRASOFTWARE_RISK_MANAGEMENT_GEOLOCATION_CHECK", False)
    device_fingerprinting = _get_bool_env("DITRASOFTWARE_RISK_MANAGEMENT_DEVICE_FINGERPRINTING", False)
    anomaly_detection = _get_bool_env("DITRASOFTWARE_RISK_MANAGEMENT_ANOMALY_DETECTION", False)
    step_up_auth_on_risk = _get_bool_env("DITRASOFTWARE_RISK_MANAGEMENT_STEP_UP_AUTH_ON_RISK", False)
    require_mfa_on_high_risk = _get_bool_env("DITRASOFTWARE_RISK_MANAGEMENT_REQUIRE_MFA_ON_HIGH_RISK", False)
    max_concurrent_sessions_raw = (os.getenv("DITRASOFTWARE_RISK_MANAGEMENT_MAX_CONCURRENT_SESSIONS") or "").strip()
    max_concurrent_sessions = int(max_concurrent_sessions_raw) if max_concurrent_sessions_raw else None
    session_timeout_minutes = _get_int_env("DITRASOFTWARE_RISK_MANAGEMENT_SESSION_TIMEOUT_MINUTES", 60)
    
    return RiskManagementSettings(
        enabled=enabled,
        ip_reputation_check=ip_reputation_check,
        geolocation_check=geolocation_check,
        device_fingerprinting=device_fingerprinting,
        anomaly_detection=anomaly_detection,
        step_up_auth_on_risk=step_up_auth_on_risk,
        require_mfa_on_high_risk=require_mfa_on_high_risk,
        max_concurrent_sessions=max_concurrent_sessions,
        session_timeout_minutes=session_timeout_minutes,
    )


def _build_compliance_settings() -> ComplianceSettings:
    """Build compliance configuration (Phase 4)."""
    enabled = _get_bool_env("DITRASOFTWARE_COMPLIANCE_ENABLED", False)
    frameworks_raw = (os.getenv("DITRASOFTWARE_COMPLIANCE_FRAMEWORKS") or "").strip()
    frameworks = tuple(f.strip() for f in frameworks_raw.split(",") if f.strip())
    gdpr_enabled = _get_bool_env("DITRASOFTWARE_COMPLIANCE_GDPR_ENABLED", False)
    gdpr_data_residency = (os.getenv("DITRASOFTWARE_COMPLIANCE_GDPR_DATA_RESIDENCY") or "").strip() or None
    hipaa_enabled = _get_bool_env("DITRASOFTWARE_COMPLIANCE_HIPAA_ENABLED", False)
    hipaa_encryption_enabled = _get_bool_env("DITRASOFTWARE_COMPLIANCE_HIPAA_ENCRYPTION_ENABLED", True)
    pci_dss_enabled = _get_bool_env("DITRASOFTWARE_COMPLIANCE_PCI_DSS_ENABLED", False)
    soc2_enabled = _get_bool_env("DITRASOFTWARE_COMPLIANCE_SOC2_ENABLED", False)
    audit_retention_years = _get_int_env("DITRASOFTWARE_COMPLIANCE_AUDIT_RETENTION_YEARS", 7)
    right_to_be_forgotten_enabled = _get_bool_env("DITRASOFTWARE_COMPLIANCE_RIGHT_TO_BE_FORGOTTEN_ENABLED", False)
    
    return ComplianceSettings(
        enabled=enabled,
        frameworks=frameworks,
        gdpr_enabled=gdpr_enabled,
        gdpr_data_residency=gdpr_data_residency,
        hipaa_enabled=hipaa_enabled,
        hipaa_encryption_enabled=hipaa_encryption_enabled,
        pci_dss_enabled=pci_dss_enabled,
        soc2_enabled=soc2_enabled,
        audit_retention_years=audit_retention_years,
        right_to_be_forgotten_enabled=right_to_be_forgotten_enabled,
    )


def get_settings() -> DitraSoftwareSettings:
    api_base_url = (os.getenv("DITRASOFTWARE_API_BASE_URL") or "").strip().rstrip("/")
    # NOTE: We intentionally allow this to be empty so the Prefab UI can still
    # render in environments where the REST backend is not configured.
    # Individual tool/resource calls will raise a clear error if the base URL
    # is missing.

    timeout_seconds_raw = (os.getenv("DITRASOFTWARE_API_TIMEOUT_SECONDS") or "30").strip()
    try:
        timeout_seconds = float(timeout_seconds_raw)
    except ValueError as e:
        raise RuntimeError(
            f"Invalid DITRASOFTWARE_API_TIMEOUT_SECONDS: {timeout_seconds_raw!r}"
        ) from e

    verify_ssl = _get_bool_env("DITRASOFTWARE_VERIFY_SSL", True)

    default_api_key = (os.getenv("DITRASOFTWARE_DEFAULT_API_KEY") or "").strip() or None
    
    # Response caching configuration (FastMCP 4.0.0+, SEP-2549)
    cache_ttl = _coerce_positive_int(os.getenv("DITRASOFTWARE_CACHE_TTL"))
    cache_scope = (os.getenv("DITRASOFTWARE_CACHE_SCOPE") or "private").strip().lower()
    if cache_scope not in {"public", "private"}:
        cache_scope = "private"
    
    # Pagination for large listings
    list_page_size = _coerce_positive_int(os.getenv("DITRASOFTWARE_LIST_PAGE_SIZE"))
    
    # Error masking for production security
    mask_error_details = _get_bool_env("DITRASOFTWARE_MASK_ERROR_DETAILS", False)
    
    # Gateway configuration
    gateway = _build_gateway_settings()
    
    # Enterprise Authentication (Phase 1-4, all disabled by default)
    oidc = _build_oidc_settings()
    audit = _build_audit_settings()
    token = _build_token_settings()
    rate_limit = _build_rate_limit_settings()
    rbac = _build_rbac_settings()
    tenant = _build_tenant_settings()
    mfa = _build_mfa_settings()
    risk_management = _build_risk_management_settings()
    compliance = _build_compliance_settings()

    return DitraSoftwareSettings(
        api_base_url=api_base_url,
        timeout_seconds=timeout_seconds,
        verify_ssl=verify_ssl,
        default_api_key=default_api_key,
        cache_ttl=cache_ttl,
        cache_scope=cache_scope,
        list_page_size=list_page_size,
        mask_error_details=mask_error_details,
        gateway=gateway,
        oidc=oidc,
        audit=audit,
        token=token,
        rate_limit=rate_limit,
        rbac=rbac,
        tenant=tenant,
        mfa=mfa,
        risk_management=risk_management,
        compliance=compliance,
    )
