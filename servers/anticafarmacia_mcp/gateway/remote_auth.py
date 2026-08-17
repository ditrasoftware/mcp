from __future__ import annotations

import base64
import os
import re
import time
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..settings import RemoteBackendSettings
from ..oauth2_1 import DoPProvider, _b64url
import json

logger = logging.getLogger(__name__)


@dataclass
class _TokenCacheEntry:
    token: str
    expires_at: float


_TOKEN_CACHE: dict[str, _TokenCacheEntry] = {}
_AUTO_AUTH_SENTINEL = "__auto__"
_DPOP_PROVIDER: DoPProvider | None = None  # OAuth 2.1 DPoP support


class GatewayAuthConfigurationError(RuntimeError):
    """Raised when remote OAuth auth is required but misconfigured."""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s or None


def _sanitize_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "_", value or "")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.upper()


def _first_set_env(names: list[str]) -> str | None:
    for name in names:
        raw = os.getenv(name)
        if raw is not None:
            cleaned = _clean(raw)
            if cleaned:
                return cleaned
    return None


def _candidate_env_names(remote: RemoteBackendSettings, key: str) -> list[str]:
    names: list[str] = []
    remote_name = _sanitize_id(remote.name)
    remote_namespace = _sanitize_id(remote.namespace)

    if remote_name:
        names.append(f"ANTICAFARMACIA_GATEWAY_REMOTE_{remote_name}_{key}")
    if remote_namespace and remote_namespace != remote_name:
        names.append(f"ANTICAFARMACIA_GATEWAY_REMOTE_{remote_namespace}_{key}")

    names.append(f"ANTICAFARMACIA_GATEWAY_REMOTE_{key}")

    if remote_name == "GOOGLE_WORKSPACE_MCP" or remote_namespace == "GOOGLE_WORKSPACE_MCP":
        if key == "ACCESS_TOKEN":
            names.append("GOOGLE_WORKSPACE_MCP_BEARER_TOKEN")
        elif key == "TOKEN_ENDPOINT":
            names.append("GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT")
        elif key == "CLIENT_ID":
            names.append("GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_ID")
        elif key == "CLIENT_SECRET":
            names.append("GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_SECRET")
        elif key == "REFRESH_TOKEN":
            names.append("GOOGLE_WORKSPACE_MCP_OAUTH_REFRESH_TOKEN")
        elif key == "SCOPE":
            names.append("GOOGLE_WORKSPACE_MCP_OAUTH_SCOPE")
        elif key == "TOKEN_ENDPOINT_AUTH_METHOD":
            names.append("GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT_AUTH_METHOD")

    return names


def _get_remote_env(remote: RemoteBackendSettings, key: str) -> str | None:
    return _first_set_env(_candidate_env_names(remote, key))


def _is_google_workspace_remote(remote: RemoteBackendSettings) -> bool:
    name = _sanitize_id(remote.name)
    namespace = _sanitize_id(remote.namespace)
    return name == "GOOGLE_WORKSPACE_MCP" or namespace == "GOOGLE_WORKSPACE_MCP"


def _effective_auth_method(remote: RemoteBackendSettings) -> str:
    method = (
        _get_remote_env(remote, "TOKEN_ENDPOINT_AUTH_METHOD")
        or "client_secret_basic"
    ).strip().lower()
    if method not in {"client_secret_basic", "client_secret_post", "none"}:
        return "client_secret_basic"
    return method


def _cache_key(
    remote: RemoteBackendSettings,
    token_endpoint: str,
    client_id: str | None,
    refresh_token: str | None,
    scope: str | None,
    method: str,
) -> str:
    rt_fingerprint = ""
    if refresh_token:
        rt_fingerprint = refresh_token[-12:]
    return (
        f"{remote.name}|{remote.namespace}|{token_endpoint}|{client_id or ''}|"
        f"{method}|{scope or ''}|{rt_fingerprint}"
    )


def _get_cached_token(key: str) -> str | None:
    entry = _TOKEN_CACHE.get(key)
    if not entry:
        return None
    if entry.expires_at <= time.time():
        _TOKEN_CACHE.pop(key, None)
        return None
    return entry.token


def _put_cached_token(key: str, token: str, expires_in_seconds: int | float | None) -> None:
    ttl = 3600
    if isinstance(expires_in_seconds, (int, float)) and expires_in_seconds > 0:
        ttl = int(expires_in_seconds)
    # Keep cache short-lived to avoid stale auth state after scope/policy changes.
    safe_ttl = min(max(ttl - 60, 60), 300)
    _TOKEN_CACHE[key] = _TokenCacheEntry(token=token, expires_at=time.time() + safe_ttl)


def _build_refresh_request(remote: RemoteBackendSettings) -> tuple[str, str, dict[str, str], dict[str, str]] | None:
    token_endpoint = _get_remote_env(remote, "TOKEN_ENDPOINT")
    refresh_token = _get_remote_env(remote, "REFRESH_TOKEN")
    if not token_endpoint or not refresh_token:
        return None

    method = _effective_auth_method(remote)
    client_id = _get_remote_env(remote, "CLIENT_ID")
    client_secret = _get_remote_env(remote, "CLIENT_SECRET")
    scope = _get_remote_env(remote, "SCOPE")

    form: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers: dict[str, str] = {
        "content-type": "application/x-www-form-urlencoded",
    }

    if scope:
        form["scope"] = scope

    if method == "client_secret_basic":
        if not client_id or not client_secret:
            raise RuntimeError(
                "Remote OAuth refresh is configured with client_secret_basic but client credentials are missing"
            )
        auth_raw = f"{client_id}:{client_secret}".encode("utf-8")
        headers["authorization"] = "Basic " + base64.b64encode(auth_raw).decode("ascii")
    elif method == "client_secret_post":
        if not client_id or not client_secret:
            raise RuntimeError(
                "Remote OAuth refresh is configured with client_secret_post but client credentials are missing"
            )
        form["client_id"] = client_id
        form["client_secret"] = client_secret
    else:
        if client_id:
            form["client_id"] = client_id

    cache_key = _cache_key(
        remote,
        token_endpoint=token_endpoint,
        client_id=client_id,
        refresh_token=refresh_token,
        scope=scope,
        method=method,
    )
    return cache_key, token_endpoint, headers, form


def _extract_token_payload(payload: Any) -> tuple[str | None, int | float | None]:
    if not isinstance(payload, dict):
        return None, None
    token = _clean(str(payload.get("access_token") or ""))
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, str):
        try:
            expires_in = float(expires_in)
        except ValueError:
            expires_in = None
    if isinstance(expires_in, (int, float)) and expires_in <= 0:
        expires_in = None
    return token, expires_in


def _is_jwt_expired(token: str) -> bool:
    """Check if a JWT bearer token is expired.
    
    Args:
        token: JWT token (format: header.payload.signature)
    
    Returns:
        True if token is expired or missing 'exp' claim, False otherwise
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return False  # Not a JWT, assume valid
        
        payload = parts[1]
        # Add padding if needed for base64 decode
        payload += "=" * (4 - len(payload) % 4)
        
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        exp = decoded.get("exp")
        
        if exp is None:
            return False  # No expiry, assume valid
        
        # Token is expired if exp is in the past (with 10-second buffer)
        return exp < (time.time() - 10)
    except Exception as e:
        logger.debug(f"Failed to decode JWT for expiry check: {e}")
        return False  # If we can't decode, assume valid


def _get_explicit_remote_auth(remote: RemoteBackendSettings) -> str | None:
    # Runtime env token is highest priority and re-evaluated per call.
    token = _get_remote_env(remote, "ACCESS_TOKEN")
    if token:
        # Check if token is a JWT and if it's expired
        if _is_jwt_expired(token):
            logger.debug(f"Explicit bearer token for {remote.name} is expired, will attempt refresh")
            return None  # Return None to trigger refresh flow below
        return token

    # Static remote.auth is lower priority and mainly a fallback.
    auth = _clean(remote.auth)
    if auth and auth != _AUTO_AUTH_SENTINEL:
        if _is_jwt_expired(auth):
            logger.debug(f"Static auth for {remote.name} is expired, will attempt refresh")
            return None
        return auth

    return None


def is_refresh_flow_configured(remote: RemoteBackendSettings) -> bool:
    token_endpoint = _get_remote_env(remote, "TOKEN_ENDPOINT")
    refresh_token = _get_remote_env(remote, "REFRESH_TOKEN")
    return bool(token_endpoint and refresh_token)


def _missing_required_refresh_env(remote: RemoteBackendSettings) -> list[str]:
    missing: list[str] = []
    method = _effective_auth_method(remote)

    if not _get_remote_env(remote, "TOKEN_ENDPOINT"):
        missing.extend(_candidate_env_names(remote, "TOKEN_ENDPOINT")[:1])
    if not _get_remote_env(remote, "REFRESH_TOKEN"):
        missing.extend(_candidate_env_names(remote, "REFRESH_TOKEN")[:1])

    if method in {"client_secret_basic", "client_secret_post"}:
        if not _get_remote_env(remote, "CLIENT_ID"):
            missing.extend(_candidate_env_names(remote, "CLIENT_ID")[:1])
        if not _get_remote_env(remote, "CLIENT_SECRET"):
            missing.extend(_candidate_env_names(remote, "CLIENT_SECRET")[:1])

    return missing


def _ensure_auth_configured(remote: RemoteBackendSettings) -> None:
    if _get_explicit_remote_auth(remote):
        return
    if is_refresh_flow_configured(remote):
        return
    if not _is_google_workspace_remote(remote):
        return

    missing = _missing_required_refresh_env(remote)
    missing_display = ", ".join(missing) if missing else "GOOGLE_WORKSPACE_MCP_BEARER_TOKEN"
    raise GatewayAuthConfigurationError(
        "Remote auth is not configured for Google Workspace MCP. "
        "Set runtime bearer token env or configure refresh-token flow. "
        f"Missing/empty: {missing_display}"
    )


def enable_dpop_for_remote_auth(enable: bool = True) -> None:
    """Enable OAuth 2.1 DPoP (Demonstration of Proof-of-Possession) for token binding.
    
    Args:
        enable: If True, token refresh requests include DPoP proofs for security
    """
    global _DPOP_PROVIDER
    if enable:
        _DPOP_PROVIDER = DoPProvider()
    else:
        _DPOP_PROVIDER = None


def _add_dpop_header_if_enabled(
    headers: dict[str, str],
    http_method: str,
    token_endpoint: str,
) -> dict[str, str]:
    """Add DPoP proof header to token request if DPoP is enabled.
    
    Args:
        headers: Existing headers
        http_method: HTTP method (POST)
        token_endpoint: Token endpoint URL
    
    Returns:
        Updated headers with DPoP-Proof if enabled
    """
    if not _DPOP_PROVIDER:
        return headers
    
    try:
        proof = _DPOP_PROVIDER.generate_proof(http_method, token_endpoint)
        headers["DPoP"] = proof.token
        return headers
    except Exception as e:
        # Log DPoP error but don't break token flow
        logger.warning(f"Failed to generate DPoP proof: {e}")
        return headers


def clear_remote_auth_cache(remote: RemoteBackendSettings) -> None:
    prefix = f"{remote.name}|{remote.namespace}|"
    keys = [k for k in _TOKEN_CACHE if k.startswith(prefix)]
    for key in keys:
        _TOKEN_CACHE.pop(key, None)


def resolve_remote_auth_sync(remote: RemoteBackendSettings, *, force_refresh: bool = False) -> str | None:
    _ensure_auth_configured(remote)

    explicit = _get_explicit_remote_auth(remote)
    if explicit:
        return explicit

    request_parts = _build_refresh_request(remote)
    if request_parts is None:
        return None

    cache_key, token_endpoint, headers, form = request_parts
    if force_refresh:
        _TOKEN_CACHE.pop(cache_key, None)

    cached = _get_cached_token(cache_key)
    if cached and not force_refresh:
        return cached

    # Add OAuth 2.1 DPoP proof if enabled
    headers = _add_dpop_header_if_enabled(headers, "POST", token_endpoint)

    timeout = httpx.Timeout(20.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.post(token_endpoint, data=form, headers=headers)

    if resp.status_code >= 400:
        body = (resp.text or "").strip()
        detail = body[:300] if body else f"HTTP {resp.status_code}"
        raise RuntimeError(f"Remote OAuth token refresh failed: {detail}")

    token, expires_in = _extract_token_payload(resp.json())
    if not token:
        raise RuntimeError("Remote OAuth token refresh did not return access_token")

    _put_cached_token(cache_key, token, expires_in)
    return token


async def resolve_remote_auth(remote: RemoteBackendSettings) -> str | None:
    _ensure_auth_configured(remote)

    explicit = _get_explicit_remote_auth(remote)
    if explicit:
        return explicit

    request_parts = _build_refresh_request(remote)
    if request_parts is None:
        return None

    cache_key, token_endpoint, headers, form = request_parts
    cached = _get_cached_token(cache_key)
    if cached:
        return cached

    # Add OAuth 2.1 DPoP proof if enabled
    headers = _add_dpop_header_if_enabled(headers, "POST", token_endpoint)

    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.post(token_endpoint, data=form, headers=headers)

    if resp.status_code >= 400:
        body = (resp.text or "").strip()
        detail = body[:300] if body else f"HTTP {resp.status_code}"
        raise RuntimeError(f"Remote OAuth token refresh failed: {detail}")

    token, expires_in = _extract_token_payload(resp.json())
    if not token:
        raise RuntimeError("Remote OAuth token refresh did not return access_token")

    _put_cached_token(cache_key, token, expires_in)
    return token


async def resolve_remote_auth_force_refresh(remote: RemoteBackendSettings) -> str | None:
    _ensure_auth_configured(remote)

    explicit = _get_explicit_remote_auth(remote)
    if explicit:
        return explicit

    request_parts = _build_refresh_request(remote)
    if request_parts is None:
        return None

    cache_key, token_endpoint, headers, form = request_parts
    _TOKEN_CACHE.pop(cache_key, None)

    # Add OAuth 2.1 DPoP proof if enabled
    headers = _add_dpop_header_if_enabled(headers, "POST", token_endpoint)

    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.post(token_endpoint, data=form, headers=headers)

    if resp.status_code >= 400:
        body = (resp.text or "").strip()
        detail = body[:300] if body else f"HTTP {resp.status_code}"
        raise RuntimeError(f"Remote OAuth token refresh failed: {detail}")

    token, expires_in = _extract_token_payload(resp.json())
    if not token:
        raise RuntimeError("Remote OAuth token refresh did not return access_token")

    _put_cached_token(cache_key, token, expires_in)
    return token