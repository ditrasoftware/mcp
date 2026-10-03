from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_context
from fastmcp.server.middleware.middleware import Middleware
import mcp.types as mt
from fastmcp.server.providers.addressing import hashed_backend_name
from fastmcp.resources.base import ResourceContent, ResourceResult
from fastmcp.tools import ToolResult
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from .rest_client import LottomaticapssAuth, LottomaticapssRestClient
from .metabase_client import MetabaseClient
from .settings import get_settings
from .version import __version__
from .card_embed import (
    CARD_EMBED_HTML,
    CARD_EMBED_META_KEY,
    CARD_EMBED_MIME,
    CARD_EMBED_URI,
    card_embed_resource_meta,
    sign_card_embed_url,
)
from .visualization import repair_visualization_payload
from .white_label import white_label_analytics_renderer
from .maps import register_maps
from .oauth import create_auth_provider
from .middleware import (
    TenantResolutionMiddleware,
    AuthEnforcementMiddleware,
    ErrorNormalizationMiddleware,
    ObservabilityMiddleware,
)
from .capability import load_capability_registry
from .gateway import (
    call_remote_tool_by_namespace,
    call_remote_tool_direct,
    call_remote_tools_in_session,
    construct_and_visualize_remote_query,
    get_runtime_remote_auth_status,
    discover_remote_tools_with_namespaces,
    get_remote_tool_suggestions,
    list_remote_tool_names,
    list_remote_tools,
    mount_remote_proxies,
    set_runtime_remote_credentials,
    probe_remote_backend,
)
from .artifacts import (
    create_local_app_providers,
    register_local_prompts,
    register_local_resources,
    register_local_tools,
)


def _patch_fastmcp_prefab_synth_domain() -> None:
    """Ensure synthesized Prefab renderer resources include `ui.domain`.

    FastMCP synthesizes per-tool renderer resources at `ui://prefab/tool/<hash>/renderer.html`.
    Some hosts (including ChatGPT's Apps manager) warn when those templates lack
    a `meta.ui.domain`.
    """
    try:
        import fastmcp.server.providers.prefab_synthesis as prefab_synthesis
    except Exception:
        return

    if getattr(prefab_synthesis, "_ditrasoftware_domain_patch", False):
        return

    original = getattr(prefab_synthesis, "_build_resource_for_tool", None)
    if not callable(original):
        return

    def _tool_hash_from_resource(resource: Any) -> str | None:
        try:
            uri = str(getattr(resource, "uri", "") or "")
        except Exception:
            return None
        m = re.search(r"ui://prefab/tool/([0-9a-f]{12})/renderer\.html", uri)
        if not m:
            return None
        return m.group(1)

    def _wrapped_build_resource_for_tool(tool: Any) -> Any:
        resource = original(tool)
        try:
            if resource is None:
                return resource

            resource_meta = getattr(resource, "meta", None) or {}
            resource_ui = resource_meta.get("ui")
            if not isinstance(resource_ui, dict):
                return resource

            mode = (os.getenv("FASTMCP_WIDGET_DOMAIN_MODE") or "claude").strip().lower()
            if mode not in {"claude", "custom", "off"}:
                mode = "claude"

            desired_domain: str | None
            if mode == "off":
                desired_domain = None
            elif mode == "custom":
                desired_domain = (
                    os.getenv("FASTMCP_APP_DOMAIN")
                    or os.getenv("PREFAB_APP_DOMAIN")
                    or ""
                ).strip() or None
            else:
                tool_hash = _tool_hash_from_resource(resource)
                if tool_hash:
                    desired_domain = f"{tool_hash}.claudemcpcontent.com"
                else:
                    desired_domain = "{hash}.claudemcpcontent.com"

            new_ui = dict(resource_ui)
            if desired_domain:
                new_ui["domain"] = desired_domain
            else:
                new_ui.pop("domain", None)
            new_meta = dict(resource_meta)
            new_meta["ui"] = new_ui

            try:
                return resource.model_copy(update={"meta": new_meta})
            except Exception:
                resource.meta = new_meta
                return resource
        except Exception:
            return resource

    prefab_synthesis._build_resource_for_tool = _wrapped_build_resource_for_tool  # type: ignore[attr-defined]
    prefab_synthesis._ditrasoftware_domain_patch = True


_patch_fastmcp_prefab_synth_domain()


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
    if ":" not in decoded:
        return None
    _, password = decoded.split(":", 1)
    password = password.strip()
    return password or None


def _basic_admin_authorized(request: Request) -> bool:
    expected = (os.getenv("LOTTOMATICAPSS_DOWNSTREAM_ADMIN_TOKEN") or "").strip()
    if not expected:
        return False
    provided = _api_key_from_basic_authorization(request.headers.get("authorization"))
    return bool(provided and hmac.compare_digest(provided, expected))


def _admin_challenge() -> PlainTextResponse:
    return PlainTextResponse(
        "Downstream connection administrator authentication required.",
        status_code=401,
        headers={"www-authenticate": 'Basic realm="Lottomatica MCP downstream connections"'},
    )


def _ctx_or_current(ctx: Context | None) -> Context | None:
    if ctx is not None:
        return ctx
    try:
        return get_context()
    except Exception:
        return None


def _header_auth(ctx: Context | None) -> LottomaticapssAuth:
    ctx2 = _ctx_or_current(ctx)
    if ctx2 is None:
        return LottomaticapssAuth()
    return _auth_from_ctx(ctx2)


def _auth_from_ctx(ctx: Context) -> LottomaticapssAuth:
    rc = ctx.request_context
    if rc is None or rc.request is None:
        return LottomaticapssAuth()

    headers = rc.request.headers
    authorization = headers.get("authorization")
    api_key = headers.get("x-api-key")
    refresh_token = headers.get("x-refresh-token")

    if not api_key:
        basic_api_key = _api_key_from_basic_authorization(authorization)
        if basic_api_key:
            api_key = basic_api_key

    return LottomaticapssAuth(
        access_token=authorization,
        api_key=api_key,
        refresh_token=refresh_token,
    )


def _auth_from_args(
    *,
    access_token: str | None = None,
    api_key: str | None = None,
    refresh_token: str | None = None,
) -> LottomaticapssAuth:
    return LottomaticapssAuth(
        access_token=access_token,
        api_key=api_key,
        refresh_token=refresh_token,
    )


def _require_auth(auth: LottomaticapssAuth) -> None:
    if auth.access_token or auth.api_key:
        return
    raise ValueError(
        "Missing auth: provide Authorization Bearer token, X-Api-Key header, or set via Auth tab."
    )


def _apply_default_auth(auth: LottomaticapssAuth, *, default_api_key: str | None) -> LottomaticapssAuth:
    if not default_api_key:
        return auth
    if auth.api_key:
        return auth
    return auth.merged(LottomaticapssAuth(api_key=default_api_key))


def _coerce_positive_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    s = value.strip()
    if not s:
        return None
    try:
        n = int(float(s))
    except ValueError:
        return None
    return n if n > 0 else None


def _env_mode(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip().lower()


def _request_fingerprint(ctx: Any) -> str:
    """Best-effort lowercased request fingerprint from headers."""
    try:
        rc = getattr(ctx, "request_context", None)
        req = getattr(rc, "request", None)
        headers = getattr(req, "headers", None) or {}
        user_agent = str(headers.get("user-agent") or "").lower()
        origin = str(headers.get("origin") or "").lower()
        referer = str(headers.get("referer") or "").lower()
        host = str(headers.get("host") or "").lower()
        return " ".join([user_agent, origin, referer, host])
    except Exception:
        return ""


def _is_chatgpt_like_request(ctx: Any) -> bool:
    blob = _request_fingerprint(ctx)
    return any(s in blob for s in ["chatgpt", "openai"])


def _is_claude_like_request(ctx: Any) -> bool:
    blob = _request_fingerprint(ctx)
    return any(s in blob for s in ["claude", "anthropic"])


def _is_gemini_like_request(ctx: Any) -> bool:
    blob = _request_fingerprint(ctx)
    return any(
        s in blob
        for s in [
            "gemini",
            "google",
            "generativelanguage",
            "vertex",
            "ai.google.dev",
        ]
    )


def _should_advertise_hashed_tool_aliases(ctx: Any) -> bool:
    """Whether to add hashed tool-name aliases in list_tools."""
    mode = _env_mode("DITRASOFTWARE_HASHED_TOOL_ALIASES", "auto")
    if mode == "always":
        return True
    if mode == "never":
        return False
    if _is_chatgpt_like_request(ctx):
        return False
    if _is_gemini_like_request(ctx):
        return False
    if _is_claude_like_request(ctx):
        return True
    return False


def _should_include_legacy_hashed_aliases(ctx: Any) -> bool:
    """Whether to expose legacy `<12-hex>_<tool>` aliases."""
    mode = _env_mode("DITRASOFTWARE_LEGACY_HASHED_TOOL_ALIASES", "auto")
    if mode == "always":
        return True
    if mode == "never":
        return False
    if _is_gemini_like_request(ctx) or _is_chatgpt_like_request(ctx):
        return False
    if _is_claude_like_request(ctx):
        return True
    return False


def _resolve_remote_route(
    *,
    route_policy: str,
    tool_name: str,
    local_tool_names: set[str],
    tool_route_overrides: dict[str, str],
    force_remote: bool,
) -> dict[str, Any]:
    override = (tool_route_overrides.get(tool_name) or "").strip().lower()
    if force_remote:
        return {
            "decision": "remote",
            "reason": "force_remote",
            "override": override or None,
            "is_local_tool": tool_name in local_tool_names,
        }

    if override == "remote":
        return {
            "decision": "remote",
            "reason": "tool_override_remote",
            "override": override,
            "is_local_tool": tool_name in local_tool_names,
        }
    if override == "local":
        return {
            "decision": "local",
            "reason": "tool_override_local",
            "override": override,
            "is_local_tool": tool_name in local_tool_names,
        }

    if route_policy == "remote_preferred":
        return {
            "decision": "remote",
            "reason": "route_policy_remote_preferred",
            "override": None,
            "is_local_tool": tool_name in local_tool_names,
        }

    if tool_name in local_tool_names:
        return {
            "decision": "local",
            "reason": "route_policy_local_preferred",
            "override": None,
            "is_local_tool": True,
        }

    return {
        "decision": "remote",
        "reason": "route_policy_local_preferred_no_local_match",
        "override": None,
        "is_local_tool": False,
    }


def create_mcp() -> FastMCP:
    settings = get_settings()
    load_capability_registry()
    client = LottomaticapssRestClient(settings)
    metabase_client = MetabaseClient(settings.metabase)

    app_providers, local_app_registry = create_local_app_providers(client, settings)

    auth_provider = create_auth_provider()
    mcp = FastMCP(
        "Lottomaticapss MCP",
        version=__version__,
        auth=auth_provider,
        cache_ttl=settings.cache_ttl,
        cache_scope=settings.cache_scope,
        list_page_size=settings.list_page_size,
        mask_error_details=settings.mask_error_details,
    )

    class _StripToolHashMiddleware(Middleware):
        _PREFAB_RENDERER_URI_RE = re.compile(r"^ui://prefab/(tool/[0-9a-f]{12}/)?renderer\\.html$")

        @staticmethod
        def _inject_ios_safari_tap_fix(html: str) -> str:
            marker = "<!-- fastmcp-ios-safari-tap-fix -->"
            if marker in html:
                return html

            css = (
                "<style>\n"
                f"{marker}\n"
                "@media (hover: none), (pointer: coarse) {\n"
                "  html, body { -webkit-tap-highlight-color: transparent; }\n"
                "  button, a, [role=\\\"button\\\"], [data-slot=\\\"button\\\"] { touch-action: manipulation; }\n"
                "  [class*='hover:']:hover { transition: none !important; }\n"
                "}\n"
                "</style>"
            )

            js = (
                "<script>\n"
                f"{marker}\n"
                "(function(){{...}})()\n"
                "</script>"
            )

            if "</head>" in html:
                return html.replace("</head>", f"{css}\n{js}\n</head>")
            return f"{css}\n{js}\n" + html

        async def on_call_tool(self, context, call_next):
            params = context.message
            name = getattr(params, "name", None)
            if isinstance(name, str):
                m = re.match(r"^(?:_)?[0-9a-f]{12}_(.+)$", name)
                if m:
                    unwrapped = m.group(1)
                    name = unwrapped
                    if hasattr(params, "model_copy"):
                        context = context.copy(message=params.model_copy(update={"name": unwrapped}))
                    else:
                        try:
                            params.name = unwrapped
                        except Exception:
                            pass
            result = await call_next(context)
            if name == "visualize_card_query" or (isinstance(name, str) and name.endswith("visualize_query")):
                repaired = repair_visualization_payload(getattr(result, "structured_content", None))
                if repaired is not None:
                    return ToolResult(content=result.content, structured_content=repaired,
                                      meta=result.meta, is_error=result.is_error)
            return result

        async def on_read_resource(self, context, call_next):
            params = context.message
            result = await call_next(context)

            if not isinstance(params, mt.ReadResourceRequestParams):
                return result

            uri = str(params.uri)
            is_prefab_renderer = bool(self._PREFAB_RENDERER_URI_RE.match(uri))
            is_analytics_mcp_app = uri.startswith("ui://ditra_analytics/metabase/")
            if not is_prefab_renderer and not is_analytics_mcp_app:
                return result

            new_contents: list[ResourceContent] = []
            changed = False
            for item in result.contents:
                content = item.content
                meta = item.meta
                is_html = isinstance(content, str) and (item.mime_type or "").startswith("text/html")
                if is_prefab_renderer and is_html:
                    content = self._inject_ios_safari_tap_fix(content)
                    changed = changed or content != item.content
                if is_analytics_mcp_app and is_html:
                    content = white_label_analytics_renderer(content)
                    changed = changed or content != item.content
                if is_analytics_mcp_app:
                    ui_meta = (meta or {}).get("ui") if isinstance(meta, dict) else None
                    if isinstance(ui_meta, dict) and not ui_meta.get("domain"):
                        updated_meta = dict(meta or {})
                        updated_ui = dict(ui_meta)
                        updated_ui["domain"] = "https://analytics.ditra.io"
                        updated_meta["ui"] = updated_ui
                        meta = updated_meta
                        changed = True
                new_contents.append(ResourceContent(content, mime_type=item.mime_type, meta=meta))

            if not changed:
                return result
            return ResourceResult(contents=new_contents, meta=result.meta)

        async def on_list_tools(self, context, call_next):
            tools = list(await call_next(context))
            remotes_by_namespace = {
                remote.namespace: remote
                for remote in settings.gateway.remotes
            }
            rewritten_tools = []
            for tool in tools:
                name = getattr(tool, "name", "")
                meta = getattr(tool, "meta", None)
                if not isinstance(name, str) or not isinstance(meta, dict):
                    rewritten_tools.append(tool)
                    continue

                matching_namespace = next(
                    (
                        namespace
                        for namespace in remotes_by_namespace
                        if name.startswith(f"{namespace}_")
                    ),
                    None,
                )
                resource_uri = meta.get("ui", {}).get("resourceUri")
                if not matching_namespace or not isinstance(resource_uri, str) or not resource_uri.startswith("ui://"):
                    rewritten_tools.append(tool)
                    continue

                rewritten_meta = dict(meta)
                rewritten_ui = dict(meta["ui"])
                rewritten_ui["resourceUri"] = (
                    f"ui://{matching_namespace}/{resource_uri.removeprefix('ui://')}"
                )
                rewritten_meta["ui"] = rewritten_ui
                rewritten_tools.append(tool.model_copy(update={"meta": rewritten_meta}))

            tools = rewritten_tools
            seen = {t.name for t in tools}

            if not _should_advertise_hashed_tool_aliases(context):
                return tools

            app_names_for_hash = ["Lottomaticapss"]
            include_legacy = _should_include_legacy_hashed_aliases(context)
            for t in list(tools):
                for app_name_for_hash in app_names_for_hash:
                    hashed = hashed_backend_name(app_name_for_hash, t.name)

                    safe_hashed = f"_{hashed}"
                    if safe_hashed not in seen:
                        tools.append(t.model_copy(update={"name": safe_hashed}))
                        seen.add(safe_hashed)

                    if include_legacy and hashed not in seen:
                        tools.append(t.model_copy(update={"name": hashed}))
                        seen.add(hashed)
            return tools

    # Register enterprise middleware stack (order matters!)
    # 1. Observability first (captures all requests)
    mcp.add_middleware(ObservabilityMiddleware())

    # 2. Tenant resolution (needed by downstream middleware)
    mcp.add_middleware(TenantResolutionMiddleware())

    # 3. Auth enforcement (needs tenant context)
    mcp.add_middleware(AuthEnforcementMiddleware())

    # 4. Error normalization (catches all errors)
    mcp.add_middleware(ErrorNormalizationMiddleware())

    # 5. FastMCP compatibility (tool hash stripping)
    mcp.add_middleware(_StripToolHashMiddleware())

    # Health check endpoint for HTTP transport (useful for load balancers, Kubernetes)
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> PlainTextResponse:
        """Simple health check endpoint.

        Returns:
            200 OK if the server is running (the generic REST backend is
            optional; the Ditra Analytics/Metabase integration is configured
            separately and checked lazily per tool call)
        """
        return PlainTextResponse("OK")

    analytics_remote = next(
        (remote for remote in settings.gateway.remotes if remote.name == "ditra-analytics"),
        None,
    )
    oauth_state: dict[str, dict[str, str]] = {}
    downstream_callback = "/admin/downstreams/ditra-analytics/callback"
    default_analytics_scopes = (
        "agent:collection:create agent:dashboard:create agent:dashboard:update "
        "agent:metric:create agent:metric:update agent:query agent:query:construct "
        "agent:query:execute agent:question:create agent:question:execute "
        "agent:question:update agent:resource:read agent:search agent:sql:construct "
        "agent:sql:execute agent:viz:mcp-ui:drill-through agent:viz:mcp-ui:query"
    )

    @mcp.custom_route("/admin/downstreams/ditra-analytics/status", methods=["GET"])
    async def analytics_connection_status(request: Request) -> JSONResponse:
        if not _basic_admin_authorized(request):
            return _admin_challenge()
        if analytics_remote is None:
            return JSONResponse({"configured": False, "error": "ditra-analytics remote is not configured"}, status_code=404)
        return JSONResponse(
            {
                "remote": analytics_remote.name,
                "namespace": analytics_remote.namespace,
                "auth": get_runtime_remote_auth_status(analytics_remote),
                "mounted": any(remote.name == analytics_remote.name for remote in mounted_remotes),
                "restart_required_for_mount": settings.gateway.mount_on_startup
                and not any(remote.name == analytics_remote.name for remote in mounted_remotes),
            }
        )

    @mcp.custom_route("/admin/downstreams/ditra-analytics/connect", methods=["GET"])
    async def connect_ditra_analytics(request: Request) -> RedirectResponse | PlainTextResponse:
        if not _basic_admin_authorized(request):
            return _admin_challenge()
        callback_url = f"{(os.getenv('LOTTOMATICAPSS_MCP_BASE_URL') or '').rstrip('/')}{downstream_callback}"
        if analytics_remote is None or not callback_url.startswith("https://"):
            return PlainTextResponse("Configure the Ditra Analytics remote and HTTPS LOTTOMATICAPSS_MCP_BASE_URL first.", status_code=503)
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        state = secrets.token_urlsafe(32)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                registration = await client.post(
                    "https://analytics.ditra.io/oauth/register",
                    json={
                        "client_name": "Lottomatica PSS MCP Gateway",
                        "redirect_uris": [callback_url],
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                        "token_endpoint_auth_method": "client_secret_basic",
                    },
                )
                registration.raise_for_status()
                credentials = registration.json()
        except Exception as exc:
            return PlainTextResponse(f"Analytics client registration failed: {exc}", status_code=502)
        client_id = str(credentials.get("client_id") or "").strip()
        client_secret = str(credentials.get("client_secret") or "").strip()
        if not client_id or not client_secret:
            return PlainTextResponse("Analytics registration response omitted client credentials.", status_code=502)
        oauth_state[state] = {"verifier": verifier, "client_id": client_id, "client_secret": client_secret}
        scopes = (
            os.getenv("LOTTOMATICAPSS_DITRA_ANALYTICS_OAUTH_SCOPES")
            or default_analytics_scopes
        ).strip()
        oauth_state[state]["scopes"] = scopes
        authorize_url = "https://analytics.ditra.io/oauth/authorize?" + urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": callback_url,
            "scope": scopes, "resource": analytics_remote.url, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return RedirectResponse(authorize_url, status_code=302)

    @mcp.custom_route(downstream_callback, methods=["GET"])
    async def complete_ditra_analytics_connection(request: Request) -> HTMLResponse:
        state = request.query_params.get("state") or ""
        code = request.query_params.get("code") or ""
        pending = oauth_state.pop(state, None)
        if not pending or not code or request.query_params.get("error"):
            return HTMLResponse("<h1>Analytics connection failed</h1><p>Invalid, expired, or denied authorization callback.</p>", status_code=400)
        callback_url = f"{(os.getenv('LOTTOMATICAPSS_MCP_BASE_URL') or '').rstrip('/')}{downstream_callback}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                token = await client.post(
                    "https://analytics.ditra.io/oauth/token",
                    data={"grant_type": "authorization_code", "code": code, "redirect_uri": callback_url, "code_verifier": pending["verifier"], "resource": analytics_remote.url if analytics_remote else ""},
                    auth=(pending["client_id"], pending["client_secret"]),
                )
                token.raise_for_status()
                payload = token.json()
        except Exception as exc:
            return HTMLResponse(f"<h1>Analytics connection failed</h1><p>Token exchange failed: {exc}</p>", status_code=502)
        refresh_token = str(payload.get("refresh_token") or "").strip()
        if analytics_remote is None or not refresh_token:
            return HTMLResponse("<h1>Analytics connection failed</h1><p>No refresh token was returned.</p>", status_code=502)
        set_runtime_remote_credentials(analytics_remote, {"TOKEN_ENDPOINT": "https://analytics.ditra.io/oauth/token", "REFRESH_TOKEN": refresh_token, "CLIENT_ID": pending["client_id"], "CLIENT_SECRET": pending["client_secret"], "TOKEN_ENDPOINT_AUTH_METHOD": "client_secret_basic", "SCOPE": pending["scopes"]})
        return HTMLResponse("<h1>Ditra Analytics connected</h1><p>The gateway credentials are stored securely. Restart the Lottomatica MCP container once to mount the authenticated remote provider.</p>")

    # Resources + prompts
    local_resource_registry = register_local_resources(mcp, client, metabase_client=metabase_client)
    local_prompt_registry = register_local_prompts(mcp, settings)
    register_maps(mcp)

    mounted_remotes = mount_remote_proxies(mcp, settings.gateway)
    tool_route_overrides = dict(settings.gateway.tool_route_overrides)

    @mcp.tool()
    async def gateway_list_backends() -> dict[str, Any]:
        """Show configured and mounted remote MCP backends for orchestration diagnostics."""
        return {
            "mode": settings.gateway.mode,
            "route_policy": settings.gateway.route_policy,
            "mount_on_startup": settings.gateway.mount_on_startup,
            "allow_direct_calls": settings.gateway.allow_direct_calls,
            "direct_result_strategy": settings.gateway.direct_result_strategy,
            "advertise_mcp_apps_ui": settings.gateway.advertise_mcp_apps_ui,
            "configured": [
                {
                    "name": r.name,
                    "namespace": r.namespace,
                    "type": r.type,
                    "url": r.url,
                    "init_timeout_ms": r.init_timeout_ms,
                    "timeout_ms": r.timeout_ms,
                    "server_instructions": r.server_instructions,
                }
                for r in settings.gateway.remotes
            ],
            "mounted": [
                {"name": m.name, "namespace": m.namespace, "url": m.url} for m in mounted_remotes
            ],
        }

    @mcp.tool()
    async def gateway_call_remote_tool(
        remote_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        force_remote: bool = False,
        result_strategy: str | None = None,
    ) -> Any:
        """Call a configured remote MCP tool directly through FastMCP Client."""
        if not settings.gateway.allow_direct_calls:
            raise ValueError("Direct remote tool calls are disabled by configuration")

        decision = _resolve_remote_route(
            route_policy=settings.gateway.route_policy,
            tool_name=tool_name,
            local_tool_names=local_tool_names,
            tool_route_overrides=tool_route_overrides,
            force_remote=force_remote,
        )
        if decision["decision"] != "remote":
            raise ValueError(
                "Remote call blocked by route policy "
                f"(tool={tool_name}, reason={decision['reason']}). "
                "Use a local tool directly or set force_remote=true."
            )

        return await call_remote_tool_direct(
            settings.gateway,
            remote_name=remote_name,
            tool_name=tool_name,
            arguments=arguments,
            result_strategy=result_strategy,
        )

    @mcp.tool(
        name="refresh_ui_credential",
        meta={"ui": {"visibility": ["app"]}},
    )
    async def refresh_ui_credential() -> mt.CallToolResult:
        """Refresh the Metabase MCP Apps credential for a mounted Analytics iframe."""
        result = await call_remote_tool_direct(
            settings.gateway,
            remote_name="ditra-analytics",
            tool_name="refresh_ui_credential",
            arguments={},
            result_strategy="passthrough",
        )
        return mt.CallToolResult(
            content=result.content,
            structured_content=result.structured_content,
            is_error=result.is_error,
            meta=result.meta,
        )

    @mcp.tool(
        name="visualize_card_query",
        meta={"ui": {"resourceUri": "ui://ditra_analytics/metabase/visualize-query.html"}},
    )
    async def visualize_card_query(card_id: int) -> mt.CallToolResult:
        """Render a saved card's query in the automatic Ditra Analytics chart viewer.

        The chart type is chosen automatically from the results, so pie, area, combo and other
        saved visualizations are not preserved. Prefer visualize_card; use this only when the card
        is not published for embedding.
        """
        card = await metabase_client.get_card(card_id)
        payload = card.data
        if not isinstance(payload, dict):
            raise ValueError(f"Saved card {card_id} returned invalid metadata")
        query = payload.get("query_json") or payload.get("dataset_query")
        if not isinstance(query, dict):
            raise ValueError(f"Saved card {card_id} does not contain an MBQL query")

        visualized = await construct_and_visualize_remote_query(
            settings.gateway,
            remote_name="ditra-analytics",
            query=query,
            prompt=f"Visualize saved card {card_id}.",
        )
        return mt.CallToolResult(
            content=visualized.content,
            structured_content=visualized.structured_content,
            is_error=visualized.is_error,
            meta=visualized.meta,
        )

    @mcp.resource(
        CARD_EMBED_URI,
        name="saved_card_view",
        mime_type=CARD_EMBED_MIME,
        meta=card_embed_resource_meta(settings.metabase.site_url),
    )
    def saved_card_view() -> str:
        """MCP Apps view that renders a published saved card with its saved visualization."""
        return CARD_EMBED_HTML

    def _signed_card_meta(card_id: int) -> dict[str, Any]:
        url, expires_at = sign_card_embed_url(
            settings.metabase.site_url,
            settings.metabase.embedding_secret_key or "",
            card_id,
            ttl_seconds=settings.metabase.embed_token_ttl_seconds,
        )
        return {CARD_EMBED_META_KEY: {"url": url, "expires_at": expires_at}}

    @mcp.tool(
        name="visualize_card",
        meta={"ui": {"resourceUri": CARD_EMBED_URI}, "openai/outputTemplate": CARD_EMBED_URI,
              "openai/widgetAccessible": True},
    )
    async def visualize_card(card_id: int) -> mt.CallToolResult:
        """Show a saved card exactly as saved in Ditra Analytics (chart type, colors, labels, settings).

        Works for cards published for embedding. If the card is not published, the result says so;
        then call visualize_card_query for an automatic chart of the same data.
        """
        card = (await metabase_client.api_get_card(card_id)).data
        if not isinstance(card, dict):
            raise ValueError(f"Saved card {card_id} returned invalid metadata")
        name, display = card.get("name") or f"Card {card_id}", card.get("display")
        published = bool(card.get("enable_embedding")) and bool(settings.metabase.embedding_secret_key)
        structured = {"card_id": card_id, "name": name, "display": display, "published": published}
        if not published:
            reason = (
                "embedding is not configured on the gateway"
                if not settings.metabase.embedding_secret_key
                else "the card is not published for embedding in Ditra Analytics"
            )
            return mt.CallToolResult(
                content=[mt.TextContent(type="text", text=(
                    f"Card {card_id} '{name}' cannot be shown with its saved {display} visualization because {reason}. "
                    f"Call visualize_card_query with card_id={card_id} for an automatic chart of the same data."))],
                structured_content=structured,
            )
        return mt.CallToolResult(
            content=[mt.TextContent(type="text", text=(
                f"Showing card {card_id} '{name}' with its saved {display} visualization in the interactive UI. "
                "This is the final result; do not restate the numbers unless the user asks."))],
            structured_content=structured,
            meta=_signed_card_meta(card_id),
        )

    @mcp.tool(
        name="saved_card_embed_url",
        meta={"ui": {"visibility": ["app"]}, "openai/widgetAccessible": True},
    )
    async def saved_card_embed_url(card_id: int) -> mt.CallToolResult:
        """Issue a fresh short-lived embed link for the saved-card view."""
        if not settings.metabase.embedding_secret_key:
            raise ValueError("Saved-card embedding is not configured")
        return mt.CallToolResult(
            content=[mt.TextContent(type="text", text="ok")],
            meta=_signed_card_meta(card_id),
        )

    @mcp.tool()
    async def gateway_list_remote_tool_sources() -> dict[str, Any]:
        """Return remote backend names that can be used with gateway_call_remote_tool."""
        return {"remotes": list_remote_tool_names(settings.gateway)}

    @mcp.tool()
    async def gateway_health_check(remote_name: str | None = None) -> dict[str, Any]:
        """Probe connectivity to one or all configured remote backends."""
        targets = [remote_name] if remote_name else list_remote_tool_names(settings.gateway)

        checks: list[dict[str, Any]] = []
        for target in targets:
            try:
                checks.append(await probe_remote_backend(settings.gateway, remote_name=target))
            except Exception as exc:
                checks.append(
                    {
                        "name": target,
                        "healthy": False,
                        "error": str(exc),
                    }
                )

        return {
            "mode": settings.gateway.mode,
            "route_policy": settings.gateway.route_policy,
            "results": checks,
        }

    @mcp.tool()
    async def gateway_resolve_tool_route(
        tool_name: str,
        force_remote: bool = False,
    ) -> dict[str, Any]:
        """Show local-vs-remote route decision for a given tool name."""
        decision = _resolve_remote_route(
            route_policy=settings.gateway.route_policy,
            tool_name=tool_name,
            local_tool_names=local_tool_names,
            tool_route_overrides=tool_route_overrides,
            force_remote=force_remote,
        )
        return {
            "tool_name": tool_name,
            "route_policy": settings.gateway.route_policy,
            "tool_override": tool_route_overrides.get(tool_name),
            **decision,
        }

    @mcp.tool()
    async def gateway_list_remote_tools(remote_name: str) -> dict[str, Any]:
        """List remote tools from one backend when the backend supports listing."""
        names = await list_remote_tools(settings.gateway, remote_name=remote_name)
        return {"remote_name": remote_name, "count": len(names), "tools": names}

    @mcp.tool()
    async def gateway_get_route_policy() -> dict[str, Any]:
        """Return effective gateway route policy and per-tool overrides."""
        return {
            "mode": settings.gateway.mode,
            "route_policy": settings.gateway.route_policy,
            "direct_result_strategy": settings.gateway.direct_result_strategy,
            "tool_route_overrides": tool_route_overrides,
        }

    @mcp.tool()
    async def gateway_discover_remote_tools() -> dict[str, Any]:
        """Discover remote tools with collision-safe remote:<name>:<tool> addresses."""
        return await discover_remote_tools_with_namespaces(settings.gateway)

    @mcp.tool()
    async def gateway_call_tool_namespaced(
        full_name: str,
        arguments: dict[str, Any] | None = None,
        result_strategy: str | None = None,
    ) -> Any:
        """Call a remote tool using remote:<remote_name>:<tool_name>."""
        return await call_remote_tool_by_namespace(
            settings.gateway,
            full_name=full_name,
            arguments=arguments,
            result_strategy=result_strategy,
        )

    @mcp.tool()
    async def gateway_suggest_remote_tools(
        partial_name: str | None = None,
    ) -> dict[str, Any]:
        """Find configured remote tools by a partial name."""
        return await get_remote_tool_suggestions(
            settings.gateway,
            partial_name=partial_name,
        )

    @mcp.tool()
    async def gateway_detect_tool_collisions() -> dict[str, Any]:
        """Report remote tool-name collisions and namespaced disambiguation."""
        discovery = await discover_remote_tools_with_namespaces(settings.gateway)
        return {
            "collision_count": discovery["collision_count"],
            "collisions": discovery["collisions"],
            "resolution": "Use gateway_call_tool_namespaced with remote:<remote_name>:<tool_name>.",
        }

    local_tool_names = register_local_tools(
        mcp,
        client,
        settings,
        _ctx_or_current=_ctx_or_current,
        _header_auth=_header_auth,
        _auth_from_args=_auth_from_args,
        _require_auth=_require_auth,
        _apply_default_auth=_apply_default_auth,
        _coerce_positive_int=_coerce_positive_int,
        metabase_client=metabase_client,
    )

    @mcp.tool()
    async def registry_summary() -> dict[str, Any]:
        """Return a consolidated registry view for local and remote capabilities."""
        return {
            "local": {
                "apps": local_app_registry,
                "resources": local_resource_registry,
                "prompts": local_prompt_registry,
                "tools": {
                    "count": len(local_tool_names),
                    "names": sorted(local_tool_names),
                },
            },
            "remote": {
                "mode": settings.gateway.mode,
                "route_policy": settings.gateway.route_policy,
                "mount_on_startup": settings.gateway.mount_on_startup,
                "direct_result_strategy": settings.gateway.direct_result_strategy,
                "tool_route_overrides": dict(settings.gateway.tool_route_overrides),
                "configured": [
                    {
                        "name": r.name,
                        "namespace": r.namespace,
                        "type": r.type,
                        "url": r.url,
                    }
                    for r in settings.gateway.remotes
                ],
                "mounted": [
                    {"name": m.name, "namespace": m.namespace, "url": m.url}
                    for m in mounted_remotes
                ],
                "mounted_count": len(mounted_remotes),
            },
        }

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Lottomaticapss MCP (FastMCP)")
    parser.add_argument(
        "--transport",
        type=str,
        default="http",
        choices=["http", "streamable-http", "sse", "stdio"],
        help="Transport (default: http)",
    )
    parser.add_argument(
        "--stateless-http",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Use stateless Streamable HTTP mode (no server-side session tracking). "
            "This is more robust behind non-sticky reverse proxies / multiple workers."
        ),
    )
    args = parser.parse_args()

    mcp = create_mcp()
    mcp.run(transport=args.transport, stateless_http=args.stateless_http)


if __name__ == "__main__":
    main()
