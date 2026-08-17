from __future__ import annotations

import argparse
import base64
import os
import re
import time
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_context
from fastmcp.server.middleware.middleware import Middleware
import mcp.types as mt
from fastmcp.server.providers.addressing import hashed_backend_name
from fastmcp.resources.base import ResourceContent, ResourceResult
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from .rest_client import AnticaFarmaciaAuth, AnticaFarmaciaRestClient
from .settings import get_settings
from .maps import register_maps
from .oauth import create_auth_provider
from .gateway import (
    call_remote_tool_direct,
    list_remote_tool_names,
    list_remote_tools,
    mount_remote_proxies,
    probe_remote_backend,
    discover_remote_tools_with_namespaces,
    call_remote_tool_by_namespace,
    get_remote_tool_suggestions,
    discover_remote_tools_with_resilience,
    call_remote_tool_with_resilience,
    GatewayResilienceManager,
)
from .providers import (
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


def _ctx_or_current(ctx: Context | None) -> Context | None:
    if ctx is not None:
        return ctx
    try:
        return get_context()
    except Exception:
        return None


def _header_auth(ctx: Context | None) -> AnticaFarmaciaAuth:
    ctx2 = _ctx_or_current(ctx)
    if ctx2 is None:
        return AnticaFarmaciaAuth()
    return _auth_from_ctx(ctx2)


def _auth_from_ctx(ctx: Context) -> AnticaFarmaciaAuth:
    rc = ctx.request_context
    if rc is None or rc.request is None:
        return AnticaFarmaciaAuth()

    headers = rc.request.headers
    authorization = headers.get("authorization")
    api_key = headers.get("x-api-key")
    refresh_token = headers.get("x-refresh-token")

    if not api_key:
        basic_api_key = _api_key_from_basic_authorization(authorization)
        if basic_api_key:
            api_key = basic_api_key

    return AnticaFarmaciaAuth(
        access_token=authorization,
        api_key=api_key,
        refresh_token=refresh_token,
    )


def _auth_from_args(
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


def _require_auth(auth: AnticaFarmaciaAuth) -> None:
    if auth.access_token or auth.api_key:
        return
    raise ValueError(
        "Missing auth: provide Authorization Bearer token, X-Api-Key header, or set via Auth tab."
    )


def _apply_default_auth(auth: AnticaFarmaciaAuth, *, default_api_key: str | None) -> AnticaFarmaciaAuth:
    if not default_api_key:
        return auth
    if auth.api_key:
        return auth
    return auth.merged(AnticaFarmaciaAuth(api_key=default_api_key))


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
    # Be conservative for unknown clients to avoid protocol/tool-name constraints.
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


def _within_tool_name_limit(name: str, limit: int = 64) -> bool:
    """Return True when tool name fits common function-name limits."""
    return len(name) <= limit


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
    client = AnticaFarmaciaRestClient(settings)

    app_providers, local_app_registry = create_local_app_providers(client, settings)

    auth_provider = create_auth_provider()
    mcp = FastMCP(
        "AnticaFarmacia MCP",
        providers=app_providers,
        auth=auth_provider,
        cache_ttl=settings.cache_ttl,
        cache_scope=settings.cache_scope,
        list_page_size=settings.list_page_size,
        mask_error_details=settings.mask_error_details,
    )

    # Initialize resilience manager for local-first gateway isolation
    resilience_mgr = GatewayResilienceManager(
        failure_threshold=3,
        cooldown_base_ms=300_000,  # 5 min
        cooldown_max_ms=1_800_000,  # 30 min
        list_tools_timeout_ms=10_000,  # 10s per-remote for tool listing
        call_tool_timeout_ms=30_000,  # 30s per-remote for tool calls
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
                    if hasattr(params, "model_copy"):
                        context = context.copy(message=params.model_copy(update={"name": unwrapped}))
                    else:
                        try:
                            params.name = unwrapped
                        except Exception:
                            pass
            return await call_next(context)

        async def on_read_resource(self, context, call_next):
            params = context.message
            result = await call_next(context)

            if not isinstance(params, mt.ReadResourceRequestParams):
                return result

            uri = str(params.uri)
            if not self._PREFAB_RENDERER_URI_RE.match(uri):
                return result

            new_contents: list[ResourceContent] = []
            changed = False
            for item in result.contents:
                if isinstance(item.content, str) and (item.mime_type or "").startswith("text/html"):
                    injected = self._inject_ios_safari_tap_fix(item.content)
                    if injected != item.content:
                        changed = True
                    new_contents.append(ResourceContent(injected, mime_type=item.mime_type, meta=item.meta))
                else:
                    new_contents.append(item)

            if not changed:
                return result
            return ResourceResult(contents=new_contents, meta=result.meta)

        async def on_list_tools(self, context, call_next):
            tools = list(await call_next(context))
            seen = {t.name for t in tools}

            if not _should_advertise_hashed_tool_aliases(context):
                return tools

            app_names_for_hash = ["AnticaFarmacia"]  # Derived from server name for tool hash aliasing
            include_legacy = _should_include_legacy_hashed_aliases(context)
            for t in list(tools):
                for app_name_for_hash in app_names_for_hash:
                    hashed = hashed_backend_name(app_name_for_hash, t.name)

                    safe_hashed = f"_{hashed}"
                    if safe_hashed not in seen and _within_tool_name_limit(safe_hashed):
                        tools.append(t.model_copy(update={"name": safe_hashed}))
                        seen.add(safe_hashed)

                    if include_legacy and hashed not in seen and _within_tool_name_limit(hashed):
                        tools.append(t.model_copy(update={"name": hashed}))
                        seen.add(hashed)
            return tools

    mcp.add_middleware(_StripToolHashMiddleware())

    # Health check endpoint for HTTP transport (useful for load balancers, Kubernetes)
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> PlainTextResponse:
        """Liveness check endpoint that does not depend on downstream config."""
        return PlainTextResponse("OK")

    @mcp.custom_route("/ready", methods=["GET"])
    async def readiness_check(request: Request) -> JSONResponse:
        """Readiness check endpoint with lightweight configuration details."""
        return JSONResponse(
            {
                "status": "ready",
                "api_base_url_configured": bool(settings.api_base_url),
                "gateway_mode": settings.gateway.mode,
                "route_policy": settings.gateway.route_policy,
                "configured_remotes": len(settings.gateway.remotes),
                "mounted_remotes": len(mounted_remotes),
            }
        )

    # Resources + prompts
    local_resource_registry = register_local_resources(mcp, client, settings)
    local_prompt_registry = register_local_prompts(mcp)
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
        """Discover all tools on all configured remotes with namespace collision detection.

        Returns:
          - tools_by_remote: organized by remote name
          - namespaced_tools: all tools with their full unique names (remote:name:tool)
          - collisions: tool name collisions across remotes (same tool in multiple remotes)
          - collision_summary: human-readable warning about collisions
          - total_remotes: count of enabled remotes
          - total_tools: total unique tool names across all remotes
          - collision_count: number of collision groups
        """
        return await discover_remote_tools_with_namespaces(settings.gateway)

    @mcp.tool()
    async def gateway_call_tool_namespaced(
        full_name: str,
        arguments: dict[str, Any] | None = None,
        result_strategy: str | None = None,
    ) -> Any:
        """Call a remote tool using its full namespaced name.

        Namespaced tool names follow the pattern: remote:<remote_name>:<tool_name>

        Examples:
          - full_name='remote:google-workspace-mcp:list_users'
          - full_name='remote:google-toolbox-mcp:create_task'

        This approach ensures no collisions when multiple remotes have tools with the same name.
        Use gateway_discover_remote_tools to see all available namespaced tool names.
        """
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
        """Get suggestions for remote tools, optionally filtered by partial name matching.

        If partial_name is not provided, returns all available remote tools.
        If partial_name='list', returns all tools containing 'list' from any remote.

        Useful for:
          - Discovering available tools across all remotes
          - Finding tools by partial name match
          - Resolving ambiguous or colliding tool names
        """
        return await get_remote_tool_suggestions(settings.gateway, partial_name=partial_name)

    @mcp.tool()
    async def gateway_detect_tool_collisions() -> dict[str, Any]:
        """Detect and report tool name collisions across all configured remotes.

        Tool name collision occurs when multiple remotes expose tools with the same name.
        For example, both google-workspace-mcp and google-toolbox-mcp might have a 'list_users' tool.

        Returns:
          - collision_count: number of collision groups
          - collisions: {base_tool_name -> [remotes]}
          - collision_summary: human-readable warning
          - resolution: instructions for using namespaced names to avoid collisions

        To call colliding tools unambiguously, use gateway_call_tool_namespaced with the
        full namespaced name (e.g., 'remote:google-workspace-mcp:list_users').
        """
        discovery = await discover_remote_tools_with_namespaces(settings.gateway)
        collisions = discovery.get("collisions", {})

        return {
            "collision_count": len(collisions),
            "collisions": collisions,
            "collision_summary": discovery.get("collision_summary", "No collisions detected."),
            "resolution": (
                "To call a colliding tool unambiguously, use gateway_call_tool_namespaced "
                "with the format: remote:<remote_name>:<tool_name>\n"
                "Example: remote:google-workspace-mcp:list_users"
            ),
            "total_remotes": discovery.get("total_remotes"),
            "total_tools": discovery.get("total_tools"),
        }

    @mcp.tool()
    async def gateway_discover_remote_tools_resilient() -> dict[str, Any]:
        """Discover all tools on all remotes with per-remote timeout and error isolation.

        TASK 1.0 IMPLEMENTATION: Local-first resilience with gateway isolation.

        Key behaviors:
          - Each remote's tool listing has a 10s timeout (per-remote)
          - If one remote times out or fails, other remotes and LOCAL tools remain unaffected
          - Remote health status is transparently included in the response
          - Error isolation: one broken remote doesn't block local tool availability

        Returns:
          - tools_by_remote: {remote_name -> tools_list_or_error}
          - namespaced_tools: tools with full unique names (remote:name:tool)
          - remote_health: per-remote status including circuit breaker state, latency, errors
          - collisions: tool name collisions detected
          - collision_summary: human-readable warning
          - total_tools, collision_count, total_remotes: summary counts

        This is the resilience-aware version of gateway_discover_remote_tools().
        Use this for production tool discovery to ensure local tools are never blocked by remote failures.
        """
        return await discover_remote_tools_with_resilience(settings.gateway, resilience_mgr=resilience_mgr)

    @mcp.tool()
    async def gateway_remote_health_status() -> dict[str, Any]:
        """Get detailed health status for all configured remote backends.

        TASK 1.0 IMPLEMENTATION: Local-first resilience with gateway isolation.

        Returns per-remote:
          - remote_name, remote_namespace: identity
          - enabled, reachable: operational state
          - error: last error message (if reachable=false)
          - circuit_state: CLOSED (normal), OPEN (cooldown), or HALF_OPEN (recovery probe)
          - failure_count: consecutive failures before circuit opened
          - last_failure_time, last_success_time: timestamps
          - latency_ms: last observed call latency

        Use this to:
          - Check which remotes are healthy (reachable=true, circuit_state=CLOSED)
          - Detect degraded remotes (circuit_state=OPEN, awaiting cooldown)
          - Monitor latency and failure trends
          - Decide whether to prompt retry or use local fallback

        Local tools are ALWAYS available regardless of remote health.
        """
        health_status = resilience_mgr.get_all_health_status()
        return {
            "timestamp": time.time(),
            "remotes": [
                {
                    "name": health.remote_name,
                    "namespace": health.remote_namespace,
                    "enabled": health.enabled,
                    "reachable": health.reachable,
                    "error": health.error,
                    "circuit_state": health.circuit_state.value,
                    "failure_count": health.failure_count,
                    "last_failure_time": health.last_failure_time,
                    "last_success_time": health.last_success_time,
                    "latency_ms": health.latency_ms,
                }
                for health in health_status.values()
            ],
            "local_tools_available": True,
            "summary": f"{len([h for h in health_status.values() if h.reachable])}/{len(health_status)} remotes healthy",
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
            },
        }

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="AnticaFarmacia MCP (FastMCP)")
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
