from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_access_token

from .settings import Settings

_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


def _encode(value: dict[str, str | int]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode(value: str) -> dict[str, str | int]:
    return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


def issue_tenant_token(
    tenant_id: str,
    secret: str,
    ttl_seconds: int = 900,
    *,
    user_id: str,
    container_id: str,
) -> str:
    if not _TENANT_RE.fullmatch(tenant_id) or not _USER_RE.fullmatch(user_id) or not _TENANT_RE.fullmatch(container_id):
        raise ValueError("Invalid tenant, user, or container ID")
    expires = int(time.time()) + max(1, ttl_seconds)
    body = _encode({"tenant_id": tenant_id, "user_id": user_id, "container_id": container_id, "exp": expires}).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{body.decode()}.{encoded}"


def _verify_token(token: str, secret: str) -> tuple[str, str, str]:
    try:
        body_text, signature = token.split(".", 1)
        claims = _decode(body_text)
        tenant_id = str(claims["tenant_id"])
        user_id = str(claims["user_id"])
        container_id = str(claims["container_id"])
        expiry = int(claims["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ToolError("Invalid tenant token") from exc
    if not _TENANT_RE.fullmatch(tenant_id) or not _USER_RE.fullmatch(user_id) or not _TENANT_RE.fullmatch(container_id) or expiry < int(time.time()):
        raise ToolError("Expired or invalid tenant token")
    body = body_text.encode()
    expected = base64.urlsafe_b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode().rstrip("=")
    if not hmac.compare_digest(signature, expected):
        raise ToolError("Invalid tenant token")
    return tenant_id, user_id, container_id


@dataclass(frozen=True)
class TenantIdentity:
    tenant_id: str
    user_id: str
    container_id: str


def resolve_tenant(ctx: Context | None, requested_tenant_id: str | None, settings: Settings) -> TenantIdentity:
    headers = {}
    request = None
    if ctx and ctx.request_context and ctx.request_context.request:
        request = ctx.request_context.request
        headers = request.headers
    auth_info = None
    try:
        auth_info = get_access_token()
    except RuntimeError:
        pass
    claims = getattr(auth_info, "claims", None) or {}
    if claims:
        token_tenant = str(claims.get("tenant_id") or claims.get("tenant") or "").strip()
        token_user = str(claims.get("user_id") or claims.get("sub") or getattr(auth_info, "subject", "") or "").strip()
        token_container = str(claims.get("container_id") or claims.get("ditrachat_container") or "").strip()
        if not token_container:
            raise ToolError("Authenticated token has no DitraChat container")
        if not token_tenant:
            raise ToolError("Authenticated token has no tenant")
        if not token_user or not _USER_RE.fullmatch(token_user):
            raise ToolError("Authenticated token has no valid DitraChat user")
        if requested_tenant_id and requested_tenant_id != token_tenant:
            raise ToolError("Requested tenant does not match authenticated tenant")
        return TenantIdentity(token_tenant, token_user, token_container)
    header_tenant = headers.get("x-tenant-id")
    header_token = headers.get("x-tenant-token")
    header_container = headers.get("x-ditrachat-container")
    header_user = headers.get("x-ditrachat-user")
    tenant_id = header_tenant
    user_id = header_user
    container_id = header_container or ""
    if settings.verify_tenant_tokens:
        if not header_token:
            if settings.allow_unauthenticated_local and requested_tenant_id:
                tenant_id = requested_tenant_id
            else:
                raise ToolError("Missing X-Tenant-Token")
        else:
            token_tenant, token_user, token_container = _verify_token(header_token, settings.tenant_token_secret or "")
            if header_tenant and header_tenant != token_tenant:
                raise ToolError("Tenant header does not match tenant token")
            if header_container and header_container != token_container:
                raise ToolError("DitraChat container header does not match tenant token")
            if header_user and header_user != token_user:
                raise ToolError("DitraChat user header does not match tenant token")
            tenant_id = token_tenant
            user_id = token_user
            container_id = token_container
    if not tenant_id:
        raise ToolError("Missing tenant identity")
    if not user_id:
        raise ToolError("Missing DitraChat user identity")
    if not _TENANT_RE.fullmatch(tenant_id):
        raise ToolError("Invalid tenant ID")
    if requested_tenant_id and requested_tenant_id != tenant_id:
        raise ToolError("Requested tenant does not match authenticated tenant")
    return TenantIdentity(tenant_id, user_id, container_id)
