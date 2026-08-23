from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context

from ...rest_client import AnticaFarmaciaAuth, AnticaFarmaciaRestClient
from ...settings import AnticaFarmaciaSettings


def register_local_tools(
    mcp: FastMCP,
    client: AnticaFarmaciaRestClient,
    settings: AnticaFarmaciaSettings,
    *,
    _ctx_or_current: Callable[[Context | None], Context | None],
    _header_auth: Callable[[Context | None], AnticaFarmaciaAuth],
    _auth_from_args: Callable[..., AnticaFarmaciaAuth],
    _require_auth: Callable[[AnticaFarmaciaAuth], None],
    _apply_default_auth: Callable[..., AnticaFarmaciaAuth],
    _coerce_positive_int: Callable[[int | str | None], int | None],
) -> set[str]:
    """Register AnticaFarmacia local tools."""

    local_tool_names: set[str] = set()

    @mcp.tool()
    async def local_auth_debug(ctx: Context | None = None) -> dict[str, Any]:
        """Return a non-sensitive view of inbound authentication headers."""
        ctx2 = _ctx_or_current(ctx)
        if ctx2 is None or ctx2.request_context is None or ctx2.request_context.request is None:
            return {
                "has_request": False,
                "has_authorization": False,
                "authorization_scheme": None,
                "has_x_api_key": False,
                "has_x_refresh_token": False,
            }

        headers = ctx2.request_context.request.headers
        authorization = headers.get("authorization")
        scheme: str | None = None
        if authorization and authorization.strip():
            scheme = authorization.strip().split(" ", 1)[0].lower()

        return {
            "has_request": True,
            "has_authorization": bool(authorization and authorization.strip()),
            "authorization_scheme": scheme,
            "has_x_api_key": bool(headers.get("x-api-key")),
            "has_x_refresh_token": bool(headers.get("x-refresh-token")),
            "user_agent": headers.get("user-agent"),
            "origin": headers.get("origin"),
            "host": headers.get("host"),
        }

    local_tool_names.add("local_auth_debug")

    @mcp.tool()
    async def local_gateway_summary() -> dict[str, Any]:
        """Return key local server and gateway settings for diagnostics."""
        return {
            "api_base_url_configured": bool(settings.api_base_url),
            "gateway_mode": settings.gateway.mode,
            "route_policy": settings.gateway.route_policy,
            "remotes": [
                {
                    "name": remote.name,
                    "namespace": remote.namespace,
                    "url": remote.url,
                    "enabled": remote.enabled,
                }
                for remote in settings.gateway.remotes
            ],
        }

    local_tool_names.add("local_gateway_summary")

    @mcp.tool()
    async def local_api_get(
        path: str,
        query: dict[str, Any] | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Issue a local GET request to the AnticaFarmacia REST backend."""
        normalized_path = path.strip()
        if not normalized_path.startswith("/"):
            raise ValueError("path must start with '/'")
        if normalized_path.startswith("//"):
            raise ValueError("path must be a relative API path (e.g. /orders)")

        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)

        return await client.request(
            "GET",
            normalized_path,
            params=query or {},
            auth=effective,
        )

    local_tool_names.add("local_api_get")

    @mcp.tool()
    async def local_api_post(
        path: str,
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Issue a local POST request to the AnticaFarmacia REST backend."""
        normalized_path = path.strip()
        if not normalized_path.startswith("/"):
            raise ValueError("path must start with '/'")
        if normalized_path.startswith("//"):
            raise ValueError("path must be a relative API path (e.g. /orders)")

        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "POST",
            normalized_path,
            json=payload,
            auth=effective,
        )

    local_tool_names.add("local_api_post")

    @mcp.tool()
    async def local_api_delete(
        path: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Issue a local DELETE request to the AnticaFarmacia REST backend."""
        normalized_path = path.strip()
        if not normalized_path.startswith("/"):
            raise ValueError("path must start with '/'")
        if normalized_path.startswith("//"):
            raise ValueError("path must be a relative API path (e.g. /orders/123)")

        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "DELETE",
            normalized_path,
            auth=effective,
            expect_json=False,
        )

    local_tool_names.add("local_api_delete")
    
    return local_tool_names
