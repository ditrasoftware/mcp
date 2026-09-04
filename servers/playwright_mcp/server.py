from __future__ import annotations

import argparse
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from .artifacts import ArtifactStore, content_metadata
from .browser import BrowserCapture
from .gateway import mount_native_playwright
from .oauth import create_auth_provider
from .settings import get_settings
from .tenant_auth import resolve_tenant


def create_mcp() -> FastMCP:
    settings = get_settings()
    store = ArtifactStore(settings)
    browser = BrowserCapture(settings)
    mcp = FastMCP("Multitenant Playwright Artifact MCP", auth=create_auth_provider())
    mount_native_playwright(mcp, url=settings.native_playwright_url, namespace=settings.native_playwright_namespace)

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    @mcp.tool()
    async def capture_artifact(
        url: str,
        artifact_type: str = "screenshot",
        selector: str | None = None,
        full_page: bool = False,
        retention_mode: str = "short",
        navigation_timeout_ms: int | None = None,
        wait_until: str | None = None,
        block_third_party_requests: bool | None = None,
        tenant_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Capture a public web artifact and return a tenant-scoped signed URL.

        `artifact_type` is `screenshot`, `jpeg`, `pdf`, or `html`. `short`
        returns a temporary artifact; `durable` also returns an `artifact_id`
        that can be used to refresh its URL later. The response never contains
        base64 data.
        `wait_until` defaults to `load`; use `networkidle` only when required.
        `navigation_timeout_ms` is bounded by server configuration, and optional
        third-party blocking avoids tracker connections delaying capture.
        """
        identity = resolve_tenant(ctx, tenant_id, settings)
        try:
            content_type, extension = content_metadata(artifact_type)
            content = await browser.capture(url, artifact_type, selector, full_page, navigation_timeout_ms, wait_until, block_third_party_requests)
            result = await store.put(identity.tenant_id, identity.user_id, identity.container_id, content, content_type, extension, retention_mode)
        except (ValueError, TimeoutError) as exc:
            raise ToolError(str(exc)) from exc
        result.update({"tenant_id": identity.tenant_id, "user_id": identity.user_id, "container_id": identity.container_id, "source_url": url, "artifact_type": artifact_type})
        return result

    @mcp.tool()
    async def get_artifact_url(
        artifact_id: str,
        tenant_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Refresh a signed URL for a durable artifact owned by the caller's tenant."""
        identity = resolve_tenant(ctx, tenant_id, settings)
        try:
            return await store.refresh_url(identity.tenant_id, identity.user_id, artifact_id)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    async def tenant_status(tenant_id: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
        """Return the authenticated tenant and artifact delivery configuration."""
        identity = resolve_tenant(ctx, tenant_id, settings)
        return {
            "tenant_id": identity.tenant_id,
            "user_id": identity.user_id,
            "container_id": identity.container_id,
            "storage": "gcs" if settings.gcs_bucket else "local",
            "signed_urls_enabled": bool(settings.gcs_bucket),
            "signed_url_ttl_seconds": settings.signed_url_ttl_seconds,
        }

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Multitenant Playwright Artifact MCP")
    parser.add_argument("--transport", default="http", choices=["http", "streamable-http", "sse", "stdio"])
    parser.add_argument("--stateless-http", action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args()
    create_mcp().run(transport=args.transport, stateless_http=args.stateless_http)


if __name__ == "__main__":
    main()
