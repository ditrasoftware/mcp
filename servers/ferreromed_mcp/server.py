from __future__ import annotations

import argparse
import base64
import os
import re
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_context
from fastmcp.server.middleware.middleware import Middleware
import mcp.types as mt
from fastmcp.server.providers.addressing import hashed_backend_name
from fastmcp.resources.base import ResourceContent, ResourceResult

from .rest_client import FerreroMedAuth, FerreroMedRestClient
from .settings import get_settings
from .resources.openapi import register_resources
from .prompts.templates import register_prompts
from .apps.ferreromed_app import create_ferreromed_app
from .maps import register_maps
from .oauth import create_auth_provider


def _patch_fastmcp_prefab_synth_domain() -> None:
    """Ensure synthesized Prefab renderer resources include `ui.domain`.

    FastMCP synthesizes per-tool renderer resources at `ui://prefab/tool/<hash>/renderer.html`.
    Some hosts (including ChatGPT's Apps manager) warn when those templates lack
    a `meta.ui.domain`.

    Default behavior (mode `claude`) sets the placeholder domain:
      `{hash}.claudemcpcontent.com`
    The host substitutes `{hash}` with the tool/resource hash.

    Env vars:
      - FASTMCP_WIDGET_DOMAIN_MODE=claude|custom|off
      - FASTMCP_APP_DOMAIN or PREFAB_APP_DOMAIN (used when mode=custom)
    """

    try:
        import fastmcp.server.providers.prefab_synthesis as prefab_synthesis
    except Exception:
        return

    if getattr(prefab_synthesis, "_ferreromed_domain_patch", False):
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
                # Claude-style hosts validate a concrete per-tool domain.
                # Prefer the deterministic tool hash from the synthesized resource URI.
                tool_hash = _tool_hash_from_resource(resource)
                if tool_hash:
                    desired_domain = f"{tool_hash}.claudemcpcontent.com"
                else:
                    # Fallback (should be rare): keep placeholder form.
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
    prefab_synthesis._ferreromed_domain_patch = True


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


def _header_auth(ctx: Context | None) -> FerreroMedAuth:
    ctx2 = _ctx_or_current(ctx)
    if ctx2 is None:
        return FerreroMedAuth()
    return _auth_from_ctx(ctx2)


def _auth_from_ctx(ctx: Context) -> FerreroMedAuth:
    rc = ctx.request_context
    if rc is None or rc.request is None:
        return FerreroMedAuth()

    headers = rc.request.headers
    authorization = headers.get("authorization")
    api_key = headers.get("x-api-key")
    refresh_token = headers.get("x-refresh-token")

    if not api_key:
        basic_api_key = _api_key_from_basic_authorization(authorization)
        if basic_api_key:
            api_key = basic_api_key

    return FerreroMedAuth(
        access_token=authorization,
        api_key=api_key,
        refresh_token=refresh_token,
    )


def _auth_from_args(
    *,
    access_token: str | None = None,
    api_key: str | None = None,
    refresh_token: str | None = None,
) -> FerreroMedAuth:
    return FerreroMedAuth(
        access_token=access_token,
        api_key=api_key,
        refresh_token=refresh_token,
    )


def _require_auth(auth: FerreroMedAuth) -> None:
    if auth.access_token or auth.api_key:
        return
    raise ValueError(
        "Missing auth: provide Authorization Bearer token, X-Api-Key header, or (for some Claude Desktop connectors) set OAuth Password which is sent as HTTP Basic and treated as the API key."
    )


def _apply_default_auth(auth: FerreroMedAuth, *, default_api_key: str | None) -> FerreroMedAuth:
    if not default_api_key:
        return auth
    # Always attach a default API key when no explicit api_key is provided.
    # This allows the REST client to fall back to API-key-only if a Bearer token
    # is present but invalid/expired (or is an MCP-local OAuth token not
    # recognized by the REST API).
    if auth.api_key:
        return auth
    return auth.merged(FerreroMedAuth(api_key=default_api_key))


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


def _should_advertise_hashed_tool_aliases(ctx: Any) -> bool:
    """Whether to add hashed tool-name aliases in list_tools.

    Prefab UI calls may use deterministic hashed tool names like:
      `<12-hex>_<tool_name>`

    Some clients (notably Claude connectors) enforce an allowlist of tool names
    based on list_tools output, so we must advertise these aliases.

    Other hosts (e.g. ChatGPT) may show a noisy tool count when aliases are
    included. In those cases the calls still work even if aliases are not
    listed, because this server strips the hash prefix in middleware.

    Env var:
      - FERREROMED_HASHED_TOOL_ALIASES=always|auto|never (default: auto)
    """

    mode = _env_mode("FERREROMED_HASHED_TOOL_ALIASES", "auto")
    if mode == "always":
        return True
    if mode == "never":
        return False

    # auto: best-effort detection from request headers.
    try:
        rc = getattr(ctx, "request_context", None)
        req = getattr(rc, "request", None)
        headers = getattr(req, "headers", None) or {}
        user_agent = str(headers.get("user-agent") or "").lower()
        origin = str(headers.get("origin") or "").lower()
        referer = str(headers.get("referer") or "").lower()
        blob = " ".join([user_agent, origin, referer])
    except Exception:
        blob = ""

    # If we can tell it's ChatGPT/OpenAI, hide aliases to reduce UI noise.
    if any(s in blob for s in ["chatgpt", "openai"]):
        return False

    # If we can tell it's Claude/Anthropic, include aliases for strict allowlisting.
    if any(s in blob for s in ["claude", "anthropic"]):
        return True

    # Default safe choice: include aliases (keeps strict clients working).
    return True


def create_mcp() -> FastMCP:
    settings = get_settings()
    client = FerreroMedRestClient(settings)

    app_provider = create_ferreromed_app(client, settings)

    auth_provider = create_auth_provider()
    mcp = FastMCP("FerreroMed MCP", providers=[app_provider], auth=auth_provider)

    class _StripToolHashMiddleware(Middleware):
        _PREFAB_RENDERER_URI_RE = re.compile(r"^ui://prefab/(tool/[0-9a-f]{12}/)?renderer\\.html$")

        @staticmethod
        def _inject_ios_safari_tap_fix(html: str) -> str:
            marker = "<!-- fastmcp-ios-safari-tap-fix -->"
            if marker in html:
                return html

            # This is a targeted mitigation for iOS Safari's well-known
            # "first tap triggers hover, second tap triggers click" behavior.
            # We inject a tiny script into the Prefab renderer shell so it
            # applies to all Prefab UI components (buttons, tabs, etc.).
            css = (
                "<style>\n"
                f"{marker}\n"
                "@media (hover: none), (pointer: coarse) {\n"
                "  html, body { -webkit-tap-highlight-color: transparent; }\n"
                "  button, a, [role=\\\"button\\\"], [data-slot=\\\"button\\\"] { touch-action: manipulation; }\n"
                "  /* Neutralize hover transitions on touch devices to reduce iOS hover emulation side-effects */\n"
                "  [class*='hover:']:hover { transition: none !important; }\n"
                "}\n"
                "</style>"
            )

            js = (
                "<script>\n"
                f"{marker}\n"
                "(function(){\n"
                "  var ua = (navigator && navigator.userAgent) || '';\n"
                "  var iOS = /iPad|iPhone|iPod/.test(ua);\n"
                "  var webkit = /WebKit/.test(ua);\n"
                "  var isCriOS = /CriOS/.test(ua);\n"
                "  var isFxiOS = /FxiOS/.test(ua);\n"
                "  var isIosSafari = iOS && webkit && !isCriOS && !isFxiOS;\n"
                "  if (!isIosSafari) return;\n"
                "\n"
                "  var touchMoved = false;\n"
                "  var startX = 0, startY = 0;\n"
                "  var suppressEl = null;\n"
                "  var suppressUntil = 0;\n"
                "  var syntheticDispatch = false;\n"
                "\n"
                "  document.addEventListener('touchstart', function(e){\n"
                "    touchMoved = false;\n"
                "    var t = e.touches && e.touches[0];\n"
                "    if (!t) return;\n"
                "    startX = t.clientX;\n"
                "    startY = t.clientY;\n"
                "  }, {capture:true, passive:true});\n"
                "\n"
                "  document.addEventListener('touchmove', function(e){\n"
                "    var t = e.touches && e.touches[0];\n"
                "    if (!t) return;\n"
                "    if (Math.abs(t.clientX - startX) > 10 || Math.abs(t.clientY - startY) > 10) touchMoved = true;\n"
                "  }, {capture:true, passive:true});\n"
                "\n"
                "  document.addEventListener('touchend', function(e){\n"
                "    if (touchMoved) return;\n"
                "    if (!e.target || !e.target.closest) return;\n"
                "    var el = e.target.closest('button, a, [role=\\\"button\\\"]');\n"
                "    if (!el) return;\n"
                "\n"
                "    // Mark element so we can suppress the subsequent native click if it occurs.\n"
                "    suppressEl = el;\n"
                "    suppressUntil = Date.now() + 800;\n"
                "\n"
                "    // Trigger the click immediately on first tap.\n"
                "    try { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); } catch(_) {}\n"
                "    try { el.blur && el.blur(); } catch(_) {}\n"
                "\n"
                "    syntheticDispatch = true;\n"
                "    try { el.click(); } finally { syntheticDispatch = false; }\n"
                "\n"
                "    // Prevent iOS from turning this tap into a hover-only interaction.\n"
                "    e.preventDefault();\n"
                "  }, {capture:true, passive:false});\n"
                "\n"
                "  document.addEventListener('click', function(e){\n"
                "    if (syntheticDispatch) return;\n"
                "    if (!suppressEl) return;\n"
                "    if (Date.now() > suppressUntil) { suppressEl = null; return; }\n"
                "    if (!e.target || !e.target.closest) return;\n"
                "    var el = e.target.closest('button, a, [role=\\\"button\\\"]');\n"
                "    if (el && el === suppressEl) {\n"
                "      e.preventDefault();\n"
                "      e.stopImmediatePropagation();\n"
                "      suppressEl = null;\n"
                "    }\n"
                "  }, true);\n"
                "})();\n"
                "</script>"
            )

            # Insert just before </head> if present; otherwise prepend.
            if "</head>" in html:
                return html.replace("</head>", f"{css}\n{js}\n</head>")
            return f"{css}\n{js}\n" + html

        async def on_call_tool(self, context, call_next):
            params = context.message
            if isinstance(params, mt.CallToolRequestParams):
                m = re.match(r"^[0-9a-f]{12}_(.+)$", params.name)
                if m:
                    context = context.copy(message=params.model_copy(update={"name": m.group(1)}))
            return await call_next(context)

        async def on_read_resource(self, context, call_next):
            params = context.message
            result = await call_next(context)

            if not isinstance(params, mt.ReadResourceRequestParams):
                return result

            uri = str(params.uri)
            if not self._PREFAB_RENDERER_URI_RE.match(uri):
                return result

            # Post-process Prefab renderer HTML.
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

            # Prefab UI tool calls use deterministic hashed names based on the
            # FastMCPApp name + tool name. Advertise these aliases so strict
            # clients (that only allow listed tool names) can invoke them.
            app_names_for_hash = ["FerreroMed"]
            for t in list(tools):
                for app_name_for_hash in app_names_for_hash:
                    hashed = hashed_backend_name(app_name_for_hash, t.name)
                    if hashed not in seen:
                        tools.append(t.model_copy(update={"name": hashed}))
                        seen.add(hashed)
            return tools

    mcp.add_middleware(_StripToolHashMiddleware())

    # Resources + prompts
    register_resources(mcp, client)
    register_prompts(mcp)
    register_maps(mcp)

    # -----------------
    # Auth tools
    # -----------------

    @mcp.tool()
    async def auth_debug(ctx: Context | None = None) -> dict[str, Any]:
        """Return a non-sensitive view of inbound auth.

        This tool is intentionally safe to run without credentials. It helps
        diagnose whether an MCP client is actually sending auth headers.

        Returns booleans and the Authorization scheme only (never the token/key).
        """
        ctx2 = _ctx_or_current(ctx)
        if ctx2 is None or ctx2.request_context is None or ctx2.request_context.request is None:
            return {
                "has_request": False,
                "has_authorization": False,
                "authorization_scheme": None,
                "has_x_api_key": False,
                "has_x_refresh_token": False,
                "user_agent": None,
                "origin": None,
                "referer": None,
                "host": None,
                "x_forwarded_for": None,
                "x_forwarded_proto": None,
                "accept": None,
            }

        headers = ctx2.request_context.request.headers
        authorization = headers.get("authorization")
        has_authorization = bool(authorization and authorization.strip())
        scheme: str | None = None
        if has_authorization:
            scheme = authorization.strip().split(" ", 1)[0].lower()

        x_api_key = headers.get("x-api-key")
        x_refresh = headers.get("x-refresh-token")

        # Useful for identifying which host/client is calling us.
        user_agent = headers.get("user-agent")
        origin = headers.get("origin")
        referer = headers.get("referer")
        host = headers.get("host")
        x_forwarded_for = headers.get("x-forwarded-for")
        x_forwarded_proto = headers.get("x-forwarded-proto")
        accept = headers.get("accept")

        return {
            "has_request": True,
            "has_authorization": has_authorization,
            "authorization_scheme": scheme,
            "has_x_api_key": bool(x_api_key and x_api_key.strip()),
            "has_x_refresh_token": bool(x_refresh and x_refresh.strip()),
            "user_agent": user_agent,
            "origin": origin,
            "referer": referer,
            "host": host,
            "x_forwarded_for": x_forwarded_for,
            "x_forwarded_proto": x_forwarded_proto,
            "accept": accept,
        }

    @mcp.tool()
    async def auth_login(
        email: str | None = None,
        password: str | None = None,
        provider: str | None = None,
    ) -> Any:
        """Login via FerreroMed REST API.

        - For email/password: provide both `email` and `password`.
        - For OAuth: provide `provider` (e.g. "google") to get an auth URL.
        """
        return await client.request(
            "POST",
            "/auth/login",
            json={"email": email, "password": password, "provider": provider},
            auth=None,
        )

    @mcp.tool()
    async def auth_refresh(
        refresh_token: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Refresh access token using a refresh token.

        Reads refresh token from argument or from `X-Refresh-Token` header.
        """
        header_auth = _header_auth(ctx)
        arg_auth = _auth_from_args(refresh_token=refresh_token)
        effective = header_auth.merged(arg_auth)

        if not effective.refresh_token:
            raise ValueError("Missing refresh token (arg refresh_token or X-Refresh-Token header)")

        # REST endpoint supports cookie/header/body; we use body for clarity.
        return await client.request(
            "POST",
            "/auth/refresh",
            json={"refresh_token": effective.refresh_token},
            auth=None,
            extra_headers={"x-refresh-token": effective.refresh_token},
        )

    # -----------------
    # Patients
    # -----------------

    @mcp.tool()
    async def patients_list(
        tax_id: str | None = None,
        full_name: str | None = None,
        name: str | None = None,
        surname: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        province: str | None = None,
        birth_day: str | None = None,
        page_number: int | str | None = None,
        page_size: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Search/list patients."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "GET",
            "/patients",
            params={
                "tax_id": tax_id,
                "full_name": full_name,
                "name": name,
                "surname": surname,
                "city": city,
                "zip_code": zip_code,
                "province": province,
                "birth_day": birth_day,
                "page_number": _coerce_positive_int(page_number),
                "page_size": _coerce_positive_int(page_size),
            },
            auth=effective,
        )

    @mcp.tool()
    async def patients_get(
        patient_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a patient by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/patients/{patient_id}", auth=effective)

    @mcp.tool()
    async def patients_create(
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create a patient. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("POST", "/patients", json=payload, auth=effective)

    @mcp.tool()
    async def patients_update(
        patient_id: str,
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Update a patient by id. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("PUT", f"/patients/{patient_id}", json=payload, auth=effective)

    @mcp.tool()
    async def patients_delete(
        patient_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Delete a patient by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "DELETE",
            f"/patients/{patient_id}",
            auth=effective,
            expect_json=False,
        )

    # -----------------
    # Orders
    # -----------------

    @mcp.tool()
    async def orders_list(
        unique_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        item_description: str | None = None,
        order_type: str | None = None,
        asl_code: str | None = None,
        district_id: int | None = None,
        patient_id: str | None = None,
        patient_full_name: str | None = None,
        tax_id: str | None = None,
        trip_id: str | None = None,
        auth_code: str | None = None,
        open: str | None = None,
        purchase: str | None = None,
        address: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        province: str | None = None,
        page_number: int | None = None,
        page_size: int | None = None,
        from_page: int | None = None,
        to_page: int | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Search/list orders."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "GET",
            "/orders",
            params={
                "unique_id": unique_id,
                "from_date": from_date,
                "to_date": to_date,
                "item_description": item_description,
                "order_type": order_type,
                "asl_code": asl_code,
                "district_id": district_id,
                "patient_id": patient_id,
                "patient_full_name": patient_full_name,
                "tax_id": tax_id,
                "trip_id": trip_id,
                "auth_code": auth_code,
                "open": open,
                "purchase": purchase,
                "address": address,
                "city": city,
                "zip_code": zip_code,
                "province": province,
                "page_number": page_number,
                "page_size": page_size,
                "from_page": from_page,
                "to_page": to_page,
            },
            auth=effective,
        )

    @mcp.tool()
    async def orders_get(
        order_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get an order by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/orders/{order_id}", auth=effective)

    @mcp.tool()
    async def orders_create(
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create an order. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("POST", "/orders", json=payload, auth=effective)

    @mcp.tool()
    async def orders_update(
        order_id: str,
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Update an order by id. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("PUT", f"/orders/{order_id}", json=payload, auth=effective)

    @mcp.tool()
    async def orders_delete(
        order_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Delete an order by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("DELETE", f"/orders/{order_id}", auth=effective, expect_json=False)

    # -----------------
    # Quotations
    # -----------------

    @mcp.tool()
    async def quotations_list(
        asl_code: str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List quotations (optionally filtered by ASL code)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", "/quotations", params={"asl_code": asl_code}, auth=effective)

    @mcp.tool()
    async def quotations_get(
        quotation_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a quotation by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/quotations/{quotation_id}", auth=effective)

    @mcp.tool()
    async def quotations_accept(
        quotation_id: str,
        user_upd: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Accept a quotation."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "POST",
            f"/quotations/{quotation_id}/accept",
            json={"user_upd": user_upd},
            auth=effective,
        )

    @mcp.tool()
    async def quotations_reject(
        quotation_id: str,
        user_upd: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Reject a quotation."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "POST",
            f"/quotations/{quotation_id}/reject",
            json={"user_upd": user_upd},
            auth=effective,
        )

    @mcp.tool()
    async def quotations_status_counts(
        asl_code: str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> list[dict[str, int | str]]:
        """Return quotation counts grouped by quote_status (for charts)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        rows = await client.request(
            "GET",
            "/quotations",
            params={"asl_code": asl_code},
            auth=effective,
        )

        counts: dict[str, int] = {}
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                status = str(r.get("quote_status") or "Unknown")
                counts[status] = counts.get(status, 0) + 1

        return [{"status": k, "count": v} for k, v in sorted(counts.items())]

    # -----------------
    # Trips (exclude trips_cv)
    # -----------------

    @mcp.tool()
    async def trips_list(
        business_entity: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        asl_code: str | None = None,
        district_id: int | None = None,
        patient_id: str | None = None,
        order_id: str | None = None,
        address: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        province: str | None = None,
        page_number: int | str | None = None,
        page_size: int | str | None = None,
        from_page: int | str | None = None,
        to_page: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Search/list trips."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "GET",
            "/trips",
            params={
                "business_entity": business_entity,
                "from_date": from_date,
                "to_date": to_date,
                "asl_code": asl_code,
                "district_id": district_id,
                "patient_id": patient_id,
                "order_id": order_id,
                "address": address,
                "city": city,
                "zip_code": zip_code,
                "province": province,
                "page_number": _coerce_positive_int(page_number),
                "page_size": _coerce_positive_int(page_size),
                "from_page": _coerce_positive_int(from_page),
                "to_page": _coerce_positive_int(to_page),
            },
            auth=effective,
        )

    @mcp.tool()
    async def trips_get(
        trip_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a trip by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/trips/{trip_id}", auth=effective)

    @mcp.tool()
    async def trips_create(
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create a trip. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("POST", "/trips", json=payload, auth=effective)

    @mcp.tool()
    async def trips_update(
        trip_id: str,
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Update a trip by id. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("PUT", f"/trips/{trip_id}", json=payload, auth=effective)

    @mcp.tool()
    async def trips_delete(
        trip_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Delete a trip by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("DELETE", f"/trips/{trip_id}", auth=effective)

    @mcp.tool()
    async def trips_status_counts(
        business_entity: str | None = None,
        asl_code: str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> list[dict[str, int | str]]:
        """Return trip counts grouped by trip_status (for charts)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        rows = await client.request(
            "GET",
            "/trips",
            params={
                "business_entity": business_entity,
                "asl_code": asl_code,
                "page_size": 250,
            },
            auth=effective,
        )

        counts: dict[str, int] = {}
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                status = str(r.get("trip_status") or "Unknown")
                counts[status] = counts.get(status, 0) + 1

        return [{"status": k, "count": v} for k, v in sorted(counts.items())]

    # -----------------
    # Lookups (read-only)
    # -----------------

    @mcp.tool()
    async def asls_list(
        asl_code: str | None = None,
        business_entity: str | None = None,
        max_rows: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List ASLs (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        rows = await client.request(
            "GET",
            "/asls",
            params={"asl_code": asl_code, "business_entity": business_entity},
            auth=effective,
        )

        max_n = _coerce_positive_int(max_rows)
        if max_n is not None and isinstance(rows, list):
            return rows[:max_n]
        return rows

    @mcp.tool()
    async def asls_list_text(
        asl_code: str | None = None,
        business_entity: str | None = None,
        max_rows: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> str:
        """List ASLs but return as a JSON string (copy/paste friendly)."""
        rows = await asls_list(
            asl_code=asl_code,
            business_entity=business_entity,
            max_rows=max_rows,
            access_token=access_token,
            api_key=api_key,
            ctx=ctx,
        )
        try:
            import json

            return json.dumps(rows, indent=2, ensure_ascii=False)
        except TypeError:
            return str(rows)

    @mcp.tool()
    async def asls_business_counts(
        asl_code: str | None = None,
        business_entity: str | None = None,
        max_rows: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> list[dict[str, int | str]]:
        """Count ASLs grouped by business_entity (for charts)."""
        rows = await asls_list(
            asl_code=asl_code,
            business_entity=business_entity,
            max_rows=max_rows,
            access_token=access_token,
            api_key=api_key,
            ctx=ctx,
        )

        counts: dict[str, int] = {}
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                key = str(r.get("business_entity") or "Unknown")
                counts[key] = counts.get(key, 0) + 1

        return [
            {"business_entity": k, "count": v}
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    @mcp.tool()
    async def products_list(
        unique_id: str | None = None,
        item_description: str | None = None,
        supplier_product_id: str | None = None,
        supplier_id: int | None = None,
        supplier_name: str | None = None,
        family_id: int | None = None,
        family_name: str | None = None,
        brand_id: int | None = None,
        brand_name: str | None = None,
        model_id: str | None = None,
        model_name: str | None = None,
        page_number: int | str | None = 1,
        page_size: int | str | None = 100,
        sort_by: str | None = "product_id",
        sort_direction: str | None = "ASC",
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List products (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "GET",
            "/products",
            params={
                "unique_id": unique_id,
                "item_description": item_description,
                "supplier_product_id": supplier_product_id,
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "family_id": family_id,
                "family_name": family_name,
                "brand_id": brand_id,
                "brand_name": brand_name,
                "model_id": model_id,
                "model_name": model_name,
                "page_number": _coerce_positive_int(page_number) or 1,
                "page_size": _coerce_positive_int(page_size) or 100,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
            },
            auth=effective,
        )

    @mcp.tool()
    async def products_get(
        product_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a product by id (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/products/{product_id}", auth=effective)

    @mcp.tool()
    async def inventory_list(
        product_id: str | None = None,
        warehouse_id: str | None = None,
        page_number: int | str | None = 1,
        page_size: int | str | None = 100,
        sort_by: str | None = "product_id",
        sort_direction: str | None = "ASC",
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List inventory (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "GET",
            "/inventory",
            params={
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "page_number": _coerce_positive_int(page_number) or 1,
                "page_size": _coerce_positive_int(page_size) or 100,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
            },
            auth=effective,
        )

    @mcp.tool()
    async def inventory_get(
        product_id: str,
        warehouse_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a single inventory record by ids (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "GET",
            f"/inventory/{product_id}/{warehouse_id}",
            auth=effective,
        )

    # -----------------
    # API Keys (admin-gated by REST API)
    # -----------------

    @mcp.tool()
    async def api_keys_create(
        name: str,
        scopes: list[str] | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create an API key (admin only in REST)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "POST",
            "/api-keys",
            json={"name": name, "scopes": scopes},
            auth=effective,
        )

    @mcp.tool()
    async def api_keys_list(
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List API keys (admin only in REST)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", "/api-keys", auth=effective)

    @mcp.tool()
    async def api_keys_revoke(
        api_key_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Revoke (soft-delete) an API key by id (admin only in REST)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "DELETE",
            f"/api-keys/{api_key_id}",
            auth=effective,
            expect_json=False,
        )

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="FerreroMed MCP Server (FastMCP)")
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
            "This is more robust behind non-sticky reverse proxies / multiple workers and "
            "prevents 'Session not found' errors in UI clients."
        ),
    )
    args = parser.parse_args()

    mcp = create_mcp()
    # If not explicitly provided, let FastMCP resolve from settings/env (FASTMCP_STATELESS_HTTP).
    mcp.run(transport=args.transport, stateless_http=args.stateless_http)


if __name__ == "__main__":
    main()
