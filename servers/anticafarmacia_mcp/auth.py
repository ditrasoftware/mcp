from __future__ import annotations

import base64

from fastmcp.server.context import Context
from fastmcp.exceptions import ToolError

from .rest_client import AnticaFarmaciaAuth


def _api_key_from_basic_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    raw = authorization.strip()
    if not raw.lower().startswith("basic "):
        return None
    b64 = raw[6:].strip()
    if not b64:
        return None
    try:
        decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
    except Exception:
        return None

    # Standard Basic format: username:password
    if ":" not in decoded:
        return None
    _, password = decoded.split(":", 1)
    password = password.strip()
    return password or None


def auth_from_ctx(ctx: Context | None) -> AnticaFarmaciaAuth:
    if ctx is None:
        return AnticaFarmaciaAuth()
    rc = ctx.request_context
    if rc is None or rc.request is None:
        return AnticaFarmaciaAuth()

    headers = rc.request.headers
    authorization = headers.get("authorization")
    api_key = headers.get("x-api-key")
    refresh_token = headers.get("x-refresh-token")

    # If X-Api-Key isn't present, treat the Basic password as the API key.
    if not api_key:
        basic_api_key = _api_key_from_basic_authorization(authorization)
        if basic_api_key:
            api_key = basic_api_key

    return AnticaFarmaciaAuth(
        access_token=authorization,
        api_key=api_key,
        refresh_token=refresh_token,
    )


def auth_from_args(
    *,
    access_token: str | None = None,
    api_key: str | None = None,
    refresh_token: str | None = None,
) -> AnticaFarmaciaAuth:
    return AnticaFarmaciaAuth(
        access_token=access_token,
        api_key=api_key,
        refresh_token=refresh_token,
    )


def apply_default_auth(auth: AnticaFarmaciaAuth, *, default_api_key: str | None) -> AnticaFarmaciaAuth:
    if auth.access_token or auth.api_key:
        return auth
    if default_api_key:
        return auth.merged(AnticaFarmaciaAuth(api_key=default_api_key))
    return auth


def require_auth(auth: AnticaFarmaciaAuth) -> None:
    if auth.access_token or auth.api_key:
        return
    raise ToolError(
        "Missing auth: provide an Authorization Bearer token or an X-Api-Key header, or set them in the app Auth tab."
    )
