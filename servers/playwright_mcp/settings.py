from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name}: {value!r}") from exc


@dataclass(frozen=True)
class Settings:
    native_playwright_url: str | None
    native_playwright_namespace: str
    gcs_bucket: str | None
    gcp_project: str | None
    gcp_service_account: str | None
    artifact_prefix: str
    signed_url_ttl_seconds: int
    max_signed_url_ttl_seconds: int
    short_retention_days: int
    navigation_timeout_ms: int
    max_navigation_timeout_ms: int
    navigation_wait_until: str
    block_third_party_requests: bool
    max_artifact_bytes: int
    verify_tenant_tokens: bool
    tenant_token_secret: str | None
    allow_unauthenticated_local: bool
    allow_private_networks: bool
    host: str
    port: int


def get_settings() -> Settings:
    secret = os.getenv("PLAYWRIGHT_MCP_TENANT_TOKEN_SECRET", "").strip() or None
    bucket = os.getenv("PLAYWRIGHT_MCP_GCS_BUCKET", "").strip() or None
    verify_tokens = _bool("PLAYWRIGHT_MCP_VERIFY_TENANT_TOKENS", True)
    if verify_tokens and not secret and not _bool("PLAYWRIGHT_MCP_ALLOW_UNAUTHENTICATED_LOCAL", False):
        raise RuntimeError(
            "Set PLAYWRIGHT_MCP_TENANT_TOKEN_SECRET, or explicitly enable "
            "PLAYWRIGHT_MCP_ALLOW_UNAUTHENTICATED_LOCAL for local-only testing"
        )
    if not bucket and not _bool("PLAYWRIGHT_MCP_ALLOW_LOCAL_ARTIFACTS", True):
        raise RuntimeError("Set PLAYWRIGHT_MCP_GCS_BUCKET or enable local artifacts")
    return Settings(
        native_playwright_url=os.getenv("PLAYWRIGHT_MCP_NATIVE_URL", "").strip() or None,
        native_playwright_namespace=(os.getenv("PLAYWRIGHT_MCP_NATIVE_NAMESPACE", "playwright").strip() or "playwright"),
        gcs_bucket=bucket,
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None,
        gcp_service_account=os.getenv("PLAYWRIGHT_MCP_GCP_SERVICE_ACCOUNT", "").strip() or None,
        artifact_prefix=(os.getenv("PLAYWRIGHT_MCP_ARTIFACT_PREFIX", "artifacts").strip("/") or "artifacts"),
        signed_url_ttl_seconds=min(_int("PLAYWRIGHT_MCP_SIGNED_URL_TTL_SECONDS", 900), _int("PLAYWRIGHT_MCP_MAX_SIGNED_URL_TTL_SECONDS", 3600)),
        max_signed_url_ttl_seconds=_int("PLAYWRIGHT_MCP_MAX_SIGNED_URL_TTL_SECONDS", 3600),
        short_retention_days=_int("PLAYWRIGHT_MCP_SHORT_RETENTION_DAYS", 1),
        navigation_timeout_ms=_int("PLAYWRIGHT_MCP_NAVIGATION_TIMEOUT_MS", 60000),
        max_navigation_timeout_ms=_int("PLAYWRIGHT_MCP_MAX_NAVIGATION_TIMEOUT_MS", 120000),
        navigation_wait_until=(os.getenv("PLAYWRIGHT_MCP_NAVIGATION_WAIT_UNTIL", "load").strip().lower() or "load"),
        block_third_party_requests=_bool("PLAYWRIGHT_MCP_BLOCK_THIRD_PARTY_REQUESTS", True),
        max_artifact_bytes=_int("PLAYWRIGHT_MCP_MAX_ARTIFACT_BYTES", 25 * 1024 * 1024),
        verify_tenant_tokens=verify_tokens,
        tenant_token_secret=secret,
        allow_unauthenticated_local=_bool("PLAYWRIGHT_MCP_ALLOW_UNAUTHENTICATED_LOCAL", False),
        allow_private_networks=_bool("PLAYWRIGHT_MCP_ALLOW_PRIVATE_NETWORKS", False),
        host=os.getenv("FASTMCP_HOST", "0.0.0.0"),
        port=_int("FASTMCP_PORT", 8001),
    )
