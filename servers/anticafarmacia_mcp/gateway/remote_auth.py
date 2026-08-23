from __future__ import annotations

import base64
from contextlib import contextmanager
import os
import re
import tempfile
import time
import logging
from pathlib import Path
from dataclasses import dataclass
import threading
from typing import Any

import httpx
from fastmcp.server.dependencies import get_context

from ..settings import RemoteBackendSettings
from ..oauth2_1 import DoPProvider, _b64url
import json

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None

logger = logging.getLogger(__name__)


@dataclass
class _TokenCacheEntry:
    token: str
    expires_at: float


_TOKEN_CACHE: dict[str, _TokenCacheEntry] = {}
_AUTO_AUTH_SENTINEL = "__auto__"
_DPOP_PROVIDER: DoPProvider | None = None  # OAuth 2.1 DPoP support
_RUNTIME_SECRET_STORE_LOADED = False
_RUNTIME_REMOTE_SECRETS: dict[str, dict[str, str]] = {}
_RUNTIME_SECRET_STORE_LOCK = threading.RLock()


class GatewayAuthConfigurationError(RuntimeError):
    """Raised when remote OAuth auth is required but misconfigured."""


class RemoteOAuthRefreshError(RuntimeError):
    """Raised when remote OAuth refresh fails with a classified reason."""

    def __init__(self, *, reason: str, message: str, status_code: int | None = None):
        self.reason = reason
        self.status_code = status_code
        super().__init__(message)


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


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_env(name: str) -> set[str]:
    raw = os.getenv(name)
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _runtime_remote_id(remote: RemoteBackendSettings) -> str:
    name = _sanitize_id(remote.name) or "UNKNOWN"
    namespace = _sanitize_id(remote.namespace) or "UNKNOWN"
    return f"{name}__{namespace}"


def _runtime_secret_store_path() -> str | None:
    raw = _clean(os.getenv("ANTICAFARMACIA_GATEWAY_REMOTE_AUTH_STORE_PATH"))
    return raw


def _remote_header_slug(remote: RemoteBackendSettings) -> str:
    candidate = (remote.name or remote.namespace or "remote").strip().lower()
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate).strip("-")
    return candidate or "remote"


def _request_header_value(name: str) -> str | None:
    try:
        ctx = get_context()
        rc = getattr(ctx, "request_context", None)
        req = getattr(rc, "request", None)
        headers = getattr(req, "headers", None)
        if headers is None:
            return None
        return _clean(headers.get(name))
    except Exception:
        return None


def _header_candidates(remote: RemoteBackendSettings, key: str) -> list[str]:
    slug = _remote_header_slug(remote)
    low_key = key.lower().replace("_", "-")
    return [
        f"x-remote-{slug}-{low_key}",
        f"x-remote-{low_key}",
    ]


def _get_request_remote_secret(remote: RemoteBackendSettings, key: str) -> str | None:
    for header in _header_candidates(remote, key):
        value = _request_header_value(header)
        if value:
            return value
    return None


def _dynamic_auth_only(remote: RemoteBackendSettings) -> bool:
    if _env_truthy("ANTICAFARMACIA_GATEWAY_DYNAMIC_AUTH_ONLY", default=False):
        return True
    names = _candidate_env_names(remote, "DYNAMIC_AUTH_ONLY")
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        if raw.strip().lower() in {"1", "true", "yes", "y", "on"}:
            return True
    return False


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
        if isinstance(decoded, dict):
            return decoded
        return None
    except Exception:
        return None


def _enforce_runtime_token_trust(
    remote: RemoteBackendSettings,
    *,
    token: str,
    source: str,
    key: str,
) -> None:
    issuers = _csv_env("ANTICAFARMACIA_GATEWAY_RUNTIME_AUTH_TRUSTED_ISSUERS")
    audiences = _csv_env("ANTICAFARMACIA_GATEWAY_RUNTIME_AUTH_TRUSTED_AUDIENCES")
    if not issuers and not audiences:
        return

    payload = _decode_jwt_payload(token)
    if payload is None:
        raise GatewayAuthConfigurationError(
            f"Runtime {key} for remote {remote.name} ({source}) is not a JWT, "
            "but trusted issuer/audience validation is enabled"
        )

    if issuers:
        iss = payload.get("iss")
        if not isinstance(iss, str) or iss not in issuers:
            raise GatewayAuthConfigurationError(
                f"Runtime {key} for remote {remote.name} failed issuer validation"
            )

    if audiences:
        aud = payload.get("aud")
        aud_values: set[str] = set()
        if isinstance(aud, str):
            aud_values.add(aud)
        elif isinstance(aud, list):
            aud_values = {x for x in aud if isinstance(x, str)}
        if not (aud_values & audiences):
            raise GatewayAuthConfigurationError(
                f"Runtime {key} for remote {remote.name} failed audience validation"
            )


@contextmanager
def _runtime_store_file_lock(path: Path):
    if fcntl is None:
        yield
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_runtime_secret_store_if_needed() -> None:
    global _RUNTIME_SECRET_STORE_LOADED
    with _RUNTIME_SECRET_STORE_LOCK:
        if _RUNTIME_SECRET_STORE_LOADED:
            return

        _RUNTIME_SECRET_STORE_LOADED = True
        store_path = _runtime_secret_store_path()
        if not store_path:
            return

        path = Path(store_path)
        if not path.exists():
            return

        lock_path = Path(f"{store_path}.lock")
        try:
            with _runtime_store_file_lock(lock_path):
                payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read remote auth runtime store: %s", exc)
            return

        if not isinstance(payload, dict):
            return

        loaded: dict[str, dict[str, str]] = {}
        for remote_id, secrets in payload.items():
            if not isinstance(remote_id, str) or not isinstance(secrets, dict):
                continue
            normalized: dict[str, str] = {}
            for key, value in secrets.items():
                if isinstance(key, str) and isinstance(value, str) and value.strip():
                    normalized[key] = value.strip()
            if normalized:
                loaded[remote_id] = normalized
        _RUNTIME_REMOTE_SECRETS.update(loaded)


def _persist_runtime_secret_store() -> None:
    store_path = _runtime_secret_store_path()
    if not store_path:
        return

    path = Path(store_path)
    lock_path = Path(f"{store_path}.lock")
    tmp_path: str | None = None
    try:
        with _RUNTIME_SECRET_STORE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _runtime_store_file_lock(lock_path):
                payload = json.dumps(_RUNTIME_REMOTE_SECRETS)
                fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
                with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                    temp_file.write(payload)
                os.replace(tmp_path, path)
    except Exception as exc:
        logger.warning("Failed to persist remote auth runtime store: %s", exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _get_runtime_remote_secret(remote: RemoteBackendSettings, key: str) -> str | None:
    _load_runtime_secret_store_if_needed()
    remote_id = _runtime_remote_id(remote)
    secret_map = _RUNTIME_REMOTE_SECRETS.get(remote_id)
    if not secret_map:
        return None
    raw = secret_map.get(key)
    if not raw:
        return None
    return _clean(raw)


def _set_runtime_remote_secret(remote: RemoteBackendSettings, key: str, value: str | None) -> None:
    _load_runtime_secret_store_if_needed()
    remote_id = _runtime_remote_id(remote)
    secret_map = _RUNTIME_REMOTE_SECRETS.setdefault(remote_id, {})

    cleaned = _clean(value)
    if cleaned is None:
        secret_map.pop(key, None)
    else:
        secret_map[key] = cleaned

    if not secret_map:
        _RUNTIME_REMOTE_SECRETS.pop(remote_id, None)

    _persist_runtime_secret_store()


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
    request_value = _get_request_remote_secret(remote, key)
    if request_value:
        if key in {"ACCESS_TOKEN", "REFRESH_TOKEN"}:
            _enforce_runtime_token_trust(remote, token=request_value, source="request_header", key=key)
        return request_value

    runtime_value = _get_runtime_remote_secret(remote, key)
    env_value = _first_set_env(_candidate_env_names(remote, key))

    if _dynamic_auth_only(remote) and key in {"ACCESS_TOKEN", "REFRESH_TOKEN"}:
        env_value = None

    if runtime_value and key in {"ACCESS_TOKEN", "REFRESH_TOKEN"}:
        _enforce_runtime_token_trust(remote, token=runtime_value, source="runtime_store", key=key)

    # For Google Workspace, avoid runtime refresh-token scope downgrade.
    # If both runtime and env refresh tokens are present, prefer env when the
    # runtime token advertises a strict subset of env scopes.
    if (
        key == "REFRESH_TOKEN"
        and _is_google_workspace_remote(remote)
        and runtime_value
        and env_value
    ):
        runtime_scopes = _jwt_scope_set(runtime_value)
        env_scopes = _jwt_scope_set(env_value)
        if runtime_scopes and env_scopes and runtime_scopes < env_scopes:
            logger.warning(
                "Ignoring runtime refresh token with narrower scope for remote %s",
                remote.name,
            )
            return env_value

    if runtime_value:
        return runtime_value
    return env_value


def _jwt_scope_set(token: str) -> set[str] | None:
    try:
        decoded = _decode_jwt_payload(token)
        if not decoded:
            return None
        scope_raw = decoded.get("scope")
        if not isinstance(scope_raw, str):
            return None
        scopes = {s.strip() for s in scope_raw.split() if s.strip()}
        return scopes or None
    except Exception:
        return None


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


def _extract_token_payload(payload: Any) -> tuple[str | None, int | float | None, str | None]:
    if not isinstance(payload, dict):
        return None, None, None
    token = _clean(str(payload.get("access_token") or ""))
    refresh_token = _clean(str(payload.get("refresh_token") or ""))
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, str):
        try:
            expires_in = float(expires_in)
        except ValueError:
            expires_in = None
    if isinstance(expires_in, (int, float)) and expires_in <= 0:
        expires_in = None
    return token, expires_in, refresh_token


def _parse_refresh_error_response(resp: httpx.Response) -> RemoteOAuthRefreshError:
    body = (resp.text or "").strip()
    provider_error: str | None = None
    provider_description: str | None = None

    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            raw_error = parsed.get("error")
            raw_desc = parsed.get("error_description")
            if isinstance(raw_error, str) and raw_error.strip():
                provider_error = raw_error.strip().lower()
            if isinstance(raw_desc, str) and raw_desc.strip():
                provider_description = raw_desc.strip()
    except Exception:
        pass

    reason = "http_error"
    if provider_error in {
        "invalid_grant",
        "invalid_client",
        "invalid_scope",
        "temporarily_unavailable",
    }:
        reason = provider_error
    elif resp.status_code in {401, 403}:
        reason = "unauthorized"

    details = provider_description or body or f"HTTP {resp.status_code}"
    details = details[:300]
    message = f"Remote OAuth token refresh failed [reason={reason} status={resp.status_code}]: {details}"
    return RemoteOAuthRefreshError(reason=reason, message=message, status_code=resp.status_code)


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

    # In dynamic-auth-only mode, do not fall back to static configured auth.
    if _dynamic_auth_only(remote):
        return None

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
    if _dynamic_auth_only(remote):
        missing_display = (
            "runtime x-remote-<remote>-access-token or x-remote-<remote>-refresh-token headers, "
            "or runtime secret store entries"
        )
    raise GatewayAuthConfigurationError(
        "Remote auth is not configured for Google Workspace MCP. "
        "Set trusted runtime credentials dynamically or configure refresh-token flow. "
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


def clear_remote_runtime_auth_secrets(remote: RemoteBackendSettings) -> None:
    _load_runtime_secret_store_if_needed()
    _RUNTIME_REMOTE_SECRETS.pop(_runtime_remote_id(remote), None)
    _persist_runtime_secret_store()


def get_remote_auth_runtime_status(remote: RemoteBackendSettings) -> dict[str, Any]:
    _load_runtime_secret_store_if_needed()
    remote_id = _runtime_remote_id(remote)
    cache_prefix = f"{remote.name}|{remote.namespace}|"
    cache_entry_count = len([k for k in _TOKEN_CACHE if k.startswith(cache_prefix)])

    explicit = _get_explicit_remote_auth(remote)
    configured_refresh = is_refresh_flow_configured(remote)
    runtime_map = _RUNTIME_REMOTE_SECRETS.get(remote_id, {})
    has_runtime_refresh = bool(_clean(runtime_map.get("REFRESH_TOKEN")))
    has_runtime_access = bool(_clean(runtime_map.get("ACCESS_TOKEN")))
    configured = bool(explicit) or configured_refresh or has_runtime_refresh

    if has_runtime_access or configured_refresh or bool(explicit):
        auth_state = "Authentication Ready"
    elif has_runtime_refresh:
        auth_state = "Refresh Available"
    else:
        auth_state = "Recovery Required"

    return {
        "remote_name": remote.name,
        "remote_namespace": remote.namespace,
        "has_explicit_auth": bool(explicit),
        "configured": configured,
        "auth_state": auth_state,
        "refresh_flow_configured": configured_refresh,
        "runtime_store_enabled": bool(_runtime_secret_store_path()),
        "has_runtime_refresh_token": has_runtime_refresh,
        "has_runtime_access_token": has_runtime_access,
        # UI aliases (kept alongside canonical names for compatibility)
        "runtime_refresh_token_present": has_runtime_refresh,
        "runtime_access_token_present": has_runtime_access,
        "cache_entry_count": cache_entry_count,
    }


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
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(token_endpoint, data=form, headers=headers)
    except httpx.TimeoutException as exc:
        raise RemoteOAuthRefreshError(
            reason="timeout",
            status_code=None,
            message=f"Remote OAuth token refresh failed [reason=timeout]: {exc}",
        ) from exc
    except httpx.TransportError as exc:
        raise RemoteOAuthRefreshError(
            reason="network_error",
            status_code=None,
            message=f"Remote OAuth token refresh failed [reason=network_error]: {exc}",
        ) from exc

    if resp.status_code >= 400:
        raise _parse_refresh_error_response(resp)

    token, expires_in, refresh_token = _extract_token_payload(resp.json())
    if not token:
        raise RuntimeError("Remote OAuth token refresh did not return access_token")

    if refresh_token:
        _set_runtime_remote_secret(remote, "REFRESH_TOKEN", refresh_token)

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
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(token_endpoint, data=form, headers=headers)
    except httpx.TimeoutException as exc:
        raise RemoteOAuthRefreshError(
            reason="timeout",
            status_code=None,
            message=f"Remote OAuth token refresh failed [reason=timeout]: {exc}",
        ) from exc
    except httpx.TransportError as exc:
        raise RemoteOAuthRefreshError(
            reason="network_error",
            status_code=None,
            message=f"Remote OAuth token refresh failed [reason=network_error]: {exc}",
        ) from exc

    if resp.status_code >= 400:
        raise _parse_refresh_error_response(resp)

    token, expires_in, refresh_token = _extract_token_payload(resp.json())
    if not token:
        raise RuntimeError("Remote OAuth token refresh did not return access_token")

    if refresh_token:
        _set_runtime_remote_secret(remote, "REFRESH_TOKEN", refresh_token)

    _put_cached_token(cache_key, token, expires_in)
    return token


async def resolve_remote_auth_force_refresh(
    remote: RemoteBackendSettings,
    *,
    ignore_explicit_auth: bool = True,
) -> str | None:
    _ensure_auth_configured(remote)

    if not ignore_explicit_auth:
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
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(token_endpoint, data=form, headers=headers)
    except httpx.TimeoutException as exc:
        raise RemoteOAuthRefreshError(
            reason="timeout",
            status_code=None,
            message=f"Remote OAuth token refresh failed [reason=timeout]: {exc}",
        ) from exc
    except httpx.TransportError as exc:
        raise RemoteOAuthRefreshError(
            reason="network_error",
            status_code=None,
            message=f"Remote OAuth token refresh failed [reason=network_error]: {exc}",
        ) from exc

    if resp.status_code >= 400:
        raise _parse_refresh_error_response(resp)

    token, expires_in, refresh_token = _extract_token_payload(resp.json())
    if not token:
        raise RuntimeError("Remote OAuth token refresh did not return access_token")

    if refresh_token:
        _set_runtime_remote_secret(remote, "REFRESH_TOKEN", refresh_token)

    _put_cached_token(cache_key, token, expires_in)
    return token