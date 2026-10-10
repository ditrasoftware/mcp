from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import httpx2
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.server.context import Context
from fastmcp.exceptions import MCPError

from .gateway import proxy, remote_auth
from .gateway.remote_auth import RemoteBearerAuth
from .server import _resolve_remote_route, create_mcp
from .settings import RemoteBackendSettings

UI_URI = "ui://ditra_analytics/metabase/visualize-query.html"
DRILL_URI = "ui://ditra_analytics/metabase/render-drill-through.html"
CSP = {"connectDomains": ["https://analytics.ditra.io"], "resourceDomains": ["https://analytics.ditra.io"]}
RENDERER = "<!doctype html><html><head><title>Metabase</title></head><body>metabase renderer</body></html>"


def _ditra_stub() -> FastMCP:
    stub = FastMCP("ditra-stub")

    @stub.tool()
    def construct_query(ctx: Context, query: dict, prompt: str = "") -> dict:
        return {"query_handle": f"{ctx.session_id}|h-1"}

    @stub.tool(meta={"ui": {"resourceUri": "ui://metabase/visualize-query.html"}})
    def visualize_query(ctx: Context, query_handle: str | None = None, query: dict | None = None) -> dict:
        if query_handle and "|" in query_handle and query_handle.split("|", 1)[0] != ctx.session_id:
            raise ValueError("Query handle belongs to a different session")
        constructed = {"database": 2, "lib/type": "mbql/query", "stages": [{
            "lib/type": "mbql.stage/mbql", "source-card": 470,
            "filters": [["between", {}, ["field", {}, "data_aggiudicazione_date"],
                         ["absolute-datetime", {}, "2024-01-01", "day"],
                         ["absolute-datetime", {}, "2025-12-31", "day"]]]}]}
        return {"query": base64.b64encode(json.dumps(constructed).encode()).decode(), "prompt": query_handle or ""}

    @stub.tool(meta={"ui": {"resourceUri": "ui://metabase/render-drill-through.html"}})
    def render_drill_through(handle: str = "") -> str:
        return "drill"

    @stub.tool(meta={"ui": {"visibility": ["app"]}})
    def refresh_ui_credential() -> str:
        return "refreshed"

    for uri in ("ui://metabase/visualize-query.html", "ui://metabase/render-drill-through.html"):
        stub.resource(uri, mime_type="text/html;profile=mcp-app",
                      meta={"ui": {"csp": CSP, "prefersBorder": True}})(lambda: RENDERER)
    return stub


class Upstream:
    """Ditra stand-in: bearer-protected MCP plus a rotating refresh-token endpoint."""

    def __init__(self):
        self.mcp_app = _ditra_stub().http_app(path="/mcp", stateless_http=False)
        self.reset()

    def reset(self):
        self.issued = 0
        self.valid: set[str] = set()
        self.refresh_token = "refresh-0"
        self.fail_refresh = False
        self.rejected = 0

    def revoke(self):
        self.valid.clear()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.mcp_app(scope, receive, send)
        if scope["path"] == "/oauth/token":
            return await self._token(scope, receive, send)
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        if not auth.startswith("Bearer ") or auth[7:] not in self.valid:
            self.rejected += 1
            body = json.dumps({"jsonrpc": "2.0", "id": None,
                               "error": {"code": -32603, "message": "Invalid bearer token"}}).encode()
            await send({"type": "http.response.start", "status": 401, "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer error="invalid_token"')]})
            return await send({"type": "http.response.body", "body": body})
        return await self.mcp_app(scope, receive, send)

    async def _token(self, scope, receive, send):
        raw = b""
        while True:
            message = await receive()
            raw += message.get("body", b"")
            if not message.get("more_body"):
                break
        form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        basic = dict(scope["headers"]).get(b"authorization", b"").decode()
        ok_client = basic == "Basic " + base64.b64encode(b"cid:secret").decode()
        if self.fail_refresh or not ok_client or form.get("refresh_token") != self.refresh_token:
            status, payload = 400, {"error": "invalid_grant"}
        else:
            self.issued += 1
            access = f"access-{self.issued}"
            self.valid = {access}
            self.refresh_token = f"refresh-{self.issued}"
            status, payload = 200, {"access_token": access, "expires_in": 3600,
                                    "refresh_token": self.refresh_token}
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": json.dumps(payload).encode()})


class MountedGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = Upstream()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(cls.upstream, log_level="error", lifespan="on"))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [sock]}, daemon=True)
        cls.thread.start()
        deadline = time.time() + 10
        while not cls.server.started and time.time() < deadline:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def setUp(self):
        self.upstream.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "remote-auth.json"
        self.store.write_text(json.dumps({"DITRA_ANALYTICS__DITRA_ANALYTICS": {
            "TOKEN_ENDPOINT": f"{self.base}/oauth/token", "REFRESH_TOKEN": "refresh-0",
            "CLIENT_ID": "cid", "CLIENT_SECRET": "secret",
            "TOKEN_ENDPOINT_AUTH_METHOD": "client_secret_basic"}}))
        env = {
            "LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_URL": f"{self.base}/mcp",
            "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "",
            "LOTTOMATICAPSS_GATEWAY_MOUNT_ON_STARTUP": "true",
            "LOTTOMATICAPSS_GATEWAY_ROUTE_POLICY": "local_preferred",
            "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_STORE_PATH": str(self.store),
            "LOTTOMATICAPSS_MCP_AUTH_MODE": "none",
            "DITRASOFTWARE_HASHED_TOOL_ALIASES": "never",
        }
        self.env = patch.dict(os.environ, env)
        self.env.start()
        for name in [n for n in os.environ if n.startswith("LOTTOMATICAPSS_GATEWAY_REMOTE_DITRA")]:
            os.environ.pop(name)
        self._reset_globals()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
        self._reset_globals()

    @staticmethod
    def _reset_globals():
        remote_auth._TOKEN_CACHE.clear()
        remote_auth._REFRESH_FAILURES.clear()
        remote_auth._RUNTIME_REMOTE_SECRETS = None
        remote_auth._ASYNC_REFRESH_LOCKS.clear()
        proxy._RETAINED_CLIENTS.clear()
        proxy._RETAINED_CLIENT_LOCKS.clear()

    def run_gateway(self, scenario):
        async def runner():
            gateway = create_mcp()
            try:
                async with Client(gateway) as client:
                    return await scenario(client)
            finally:
                for retained in list(proxy._RETAINED_CLIENTS.values()):
                    await retained.__aexit__(None, None, None)
        return asyncio.run(runner())

    def test_mounted_tools_list_has_namespaced_ui_metadata_and_local_tools(self):
        async def scenario(client):
            return [{t.name: t for t in (await client.list_tools_mcp()).tools} for _ in range(3)]

        for tools in self.run_gateway(scenario):
            for name in ("ditra_analytics_construct_query", "ditra_analytics_visualize_query",
                         "ditra_analytics_render_drill_through", "answer_dashboard_kpi",
                         "get_dashboard_card_data", "visualize_card", "visualize_card_query",
                         "gateway_list_backends"):
                self.assertIn(name, tools)
            self.assertEqual(tools["ditra_analytics_visualize_query"].meta["ui"]["resourceUri"], UI_URI)
            self.assertEqual(tools["ditra_analytics_render_drill_through"].meta["ui"]["resourceUri"], DRILL_URI)
            self.assertEqual(tools["visualize_card_query"].meta["ui"]["resourceUri"], UI_URI)
            self.assertEqual(tools["visualize_card"].meta["ui"]["resourceUri"], "ui://lottomaticapss/saved-card.html")
        self.assertEqual(self.upstream.issued, 1)

    def test_stale_mounted_token_is_refreshed_and_rotation_persisted(self):
        async def scenario(client):
            first = (await client.list_tools_mcp()).tools
            self.upstream.revoke()
            second = (await client.list_tools_mcp()).tools
            resources = (await client.list_resources_mcp()).resources
            return first, second, resources

        first, second, resources = self.run_gateway(scenario)
        for tools in (first, second):
            self.assertIn("ditra_analytics_visualize_query", {t.name for t in tools})
        self.assertIn(UI_URI, {str(r.uri) for r in resources})
        self.assertEqual(self.upstream.issued, 2)
        stored = json.loads(self.store.read_text())["DITRA_ANALYTICS__DITRA_ANALYTICS"]
        self.assertEqual(stored["REFRESH_TOKEN"], "refresh-2")
        self.assertNotIn("access-", self.store.read_text())

    def test_direct_visualization_and_ui_refresh_share_mounted_session(self):
        from .gateway.direct import construct_and_visualize_remote_query
        from .settings import get_settings
        async def scenario(client):
            await client.list_tools_mcp()
            retained = next(iter(proxy._RETAINED_CLIENTS.values()))
            visualized = await construct_and_visualize_remote_query(get_settings().gateway,
                remote_name="ditra-analytics", query={"database": 2}, prompt="Saved card")
            self.assertFalse(visualized.is_error)
            replay = await client.call_tool("ditra_analytics_visualize_query",
                {"query_handle": visualized.structured_content["prompt"]})
            self.assertFalse(replay.is_error)
            await client.call_tool("refresh_ui_credential", {})
            self.assertEqual(len(proxy._RETAINED_CLIENTS), 1)
            self.assertIs(next(iter(proxy._RETAINED_CLIENTS.values())), retained)
            self.assertEqual(retained.active_contexts, 1)
        self.run_gateway(scenario)
        self.assertEqual(proxy._RETAINED_CLIENTS, {})
        self.assertEqual(proxy._RETAINED_CLIENT_LOCKS, {})

    def test_query_construction_error_is_preserved_without_visualization(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from mcp import types as mt
        from .gateway import direct
        from .settings import get_settings

        error = mt.CallToolResult(isError=True, content=[mt.TextContent(
            type="text", text="Native query construction was rejected")])
        downstream = SimpleNamespace(call_tool_mcp=AsyncMock(return_value=error))

        async def call_with_client(remote, *, auth, operation):
            return await operation(downstream)

        with patch.object(direct, "_call_with_client", call_with_client):
            result = asyncio.run(direct.construct_and_visualize_remote_query(
                get_settings().gateway, remote_name="ditra-analytics",
                query={"database": 2, "type": "native", "native": {"query": "SELECT 1"}},
                prompt="Saved SQL card"))
        self.assertIs(result, error)
        downstream.call_tool_mcp.assert_awaited_once()
        self.assertEqual(downstream.call_tool_mcp.call_args.args[0], "construct_query")

    def test_retained_pool_does_not_evict_active_clients_and_is_bounded(self):
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url=f"{self.base}/mcp", auth="__auto__")
        async def scenario():
            try:
                retained = await proxy._retained_client_factory(remote=remote, timeout_seconds=5, advertise_mcp_apps_ui=True)
                async with retained:
                    retained.last_used = time.monotonic() - 1000
                    await proxy._evict_idle_clients()
                    self.assertIn(retained, proxy._RETAINED_CLIENTS.values())
                retained.last_used = time.monotonic() - 1000
                await proxy._evict_idle_clients()
                self.assertFalse(retained.is_connected())
                self.assertEqual(proxy._RETAINED_CLIENTS, {})
                with patch.object(proxy, "_MAX_RETAINED_CLIENTS", 0), self.assertRaisesRegex(RuntimeError, "capacity"):
                    await proxy._retained_client_factory(remote=remote, timeout_seconds=5, advertise_mcp_apps_ui=True)
            finally:
                await proxy.close_retained_clients()
        asyncio.run(scenario())

    def test_resources_read_returns_mcp_app_renderer(self):
        async def scenario(client):
            listed = {str(r.uri): r for r in (await client.list_resources_mcp()).resources}
            return listed, await client.read_resource_mcp(UI_URI)

        listed, result = self.run_gateway(scenario)
        self.assertEqual(listed[UI_URI].mime_type, "text/html;profile=mcp-app")
        (content,) = result.contents
        self.assertIn("<title>Ditra Analytics</title>", content.text)
        self.assertIn("MutationObserver", content.text)
        self.assertIn("metabase renderer", content.text)
        self.assertEqual(content.mime_type, "text/html;profile=mcp-app")
        self.assertEqual(content.meta["ui"]["csp"], CSP)
        self.assertEqual(content.meta["ui"]["domain"], "https://analytics.ditra.io")

    def test_downstream_auth_failure_on_resources_read_is_jsonrpc_error(self):
        self.upstream.fail_refresh = True

        async def scenario(client):
            with self.assertRaises(MCPError) as caught:
                await client.read_resource_mcp(UI_URI)
            return str(caught.exception)

        message = self.run_gateway(scenario)
        self.assertNotIn("to_mcp_result", message)
        self.assertNotIn("Internal server error", message)
        self.assertIn("visualize-query.html", message)
        self.assertEqual(self.upstream.issued, 0)

    def test_mounted_visualize_query_returns_executable_date_filters(self):
        async def scenario(client):
            return await client.call_tool_mcp("ditra_analytics_visualize_query", {"query_handle": "h-1"})

        result = self.run_gateway(scenario)
        query = json.loads(base64.b64decode(result.structured_content["query"]))
        self.assertEqual(query["stages"][0]["filters"][0][3:], ["2024-01-01", "2025-12-31"])
        self.assertEqual(result.structured_content["prompt"], "h-1")

    def test_async_file_lock_wait_does_not_block_the_event_loop(self):
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url=f"{self.base}/mcp", auth="__auto__")
        async def scenario():
            started = asyncio.Event()
            async def waiter():
                started.set()
                async with remote_auth._async_refresh_file_lock(remote):
                    return "acquired"
            with remote_auth._refresh_file_lock(remote):
                task = asyncio.create_task(waiter())
                await asyncio.wait_for(started.wait(), 1)
                progressed = asyncio.Event()
                asyncio.get_running_loop().call_soon(progressed.set)
                await asyncio.wait_for(progressed.wait(), 1)
                self.assertFalse(task.done())
            self.assertEqual(await asyncio.wait_for(task, 1), "acquired")
        asyncio.run(scenario())

    def test_refresh_and_reconnection_write_are_serialized(self):
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url=f"{self.base}/mcp", auth="__auto__")
        async_client = httpx.AsyncClient
        async def scenario():
            entered = asyncio.Event()
            release = asyncio.Event()
            async def handler(request):
                entered.set()
                await release.wait()
                return httpx.Response(200, json={"access_token": "renewed", "refresh_token": "rotated", "expires_in": 3600})
            def client(**kwargs):
                return async_client(transport=httpx.MockTransport(handler), **kwargs)
            with patch.object(remote_auth.httpx, "AsyncClient", client):
                refresh = asyncio.create_task(remote_auth.resolve_remote_auth(remote))
                await asyncio.wait_for(entered.wait(), 1)
                write = asyncio.create_task(remote_auth.set_runtime_remote_credentials_async(remote, {"REFRESH_TOKEN": "replacement"}))
                progressed = asyncio.Event()
                asyncio.get_running_loop().call_soon(progressed.set)
                await asyncio.wait_for(progressed.wait(), 1)
                self.assertFalse(write.done())
                release.set()
                self.assertEqual(await asyncio.wait_for(refresh, 1), "renewed")
                await asyncio.wait_for(write, 1)
            self.assertEqual(remote_auth._get_remote_env(remote, "REFRESH_TOKEN"), "replacement")
        asyncio.run(scenario())

    def test_concurrent_rejected_tokens_share_one_refresh(self):
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url=f"{self.base}/mcp", auth="__auto__")

        async def scenario():
            rejected = await remote_auth.resolve_remote_auth(remote)
            self.upstream.revoke()
            return await asyncio.gather(*[
                remote_auth.resolve_remote_auth_force_refresh(remote, rejected_token=rejected)
                for _ in range(20)
            ])

        tokens = asyncio.run(scenario())
        self.assertEqual(set(tokens), {"access-2"})
        self.assertEqual(self.upstream.issued, 2)

    def test_invalid_grant_blocks_further_refresh_until_reconnection(self):
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url=f"{self.base}/mcp", auth="__auto__")
        self.upstream.fail_refresh = True

        async def scenario():
            with self.assertRaisesRegex(RuntimeError, "invalid_grant"):
                await remote_auth.resolve_remote_auth(remote)
            self.upstream.fail_refresh = False
            with self.assertRaisesRegex(RuntimeError, "reconnection required"):
                await remote_auth.resolve_remote_auth(remote)
            remote_auth.clear_remote_auth_cache(remote)
            return await remote_auth.resolve_remote_auth(remote)

        self.assertEqual(asyncio.run(scenario()), "access-1")

    def test_short_lived_token_is_never_cached_past_expiry(self):
        with patch.object(remote_auth.time, "time", return_value=100):
            remote_auth._put_cached_token("short", "token", 5)
        self.assertLess(remote_auth._TOKEN_CACHE["short"].expires_at, 105)
        with patch.object(remote_auth.time, "time", return_value=105):
            self.assertIsNone(remote_auth._get_cached_token("short"))
        for lifetime in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(lifetime=lifetime), self.assertRaises(RuntimeError):
                remote_auth._extract_token_payload({"access_token": "token", "expires_in": lifetime})
        for lifetime in (None, "unknown", {}, False, float("nan")):
            with self.subTest(unknown_lifetime=lifetime):
                remote_auth._put_cached_token("short", "token", lifetime)
                self.assertIsNone(remote_auth._get_cached_token("short"))

    def test_local_preferred_routing_keeps_local_tools_local(self):
        local = {"answer_dashboard_kpi", "get_dashboard_card_data"}
        decision = _resolve_remote_route(route_policy="local_preferred", tool_name="get_dashboard_card_data",
                                         local_tool_names=local, tool_route_overrides={}, force_remote=False)
        self.assertEqual(decision["decision"], "local")
        remote = _resolve_remote_route(route_policy="local_preferred", tool_name="construct_query",
                                       local_tool_names=local, tool_route_overrides={}, force_remote=False)
        self.assertEqual(remote["decision"], "remote")


class ConnectionRegistryTests(unittest.TestCase):
    def test_tenant_self_service_creates_isolated_connection_from_fixed_template(self):
        from .gateway.connections import ConnectionRegistry, Principal
        issuer = "https://securetoken.google.com/project"
        tenant = "tenant"
        template = {"id": "ditra-policy-template", "remote": "ditra-analytics", "mode": "delegated",
            "tenant": tenant, "issuer": issuer, "subjects": ["existing-owner"],
            "credential_ref": "existing-owner-grant", "tools": ["search", "visualize_card_echarts"],
            "resources": ["ui://ditra_analytics/metabase/echarts-saved-card.html"],
            "required_scopes": ["mcp:access"], "downstream_account_id": "123"}
        env = {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([template]),
               "LOTTOMATICAPSS_GATEWAY_DITRA_SELF_SERVICE": "true",
               "LOTTOMATICAPSS_MCP_AUTH_MODE": "gcip", "LOTTOMATICAPSS_GCIP_ACCESS_MODE": "tenant",
               "LOTTOMATICAPSS_GCIP_PROJECT_ID": "project", "LOTTOMATICAPSS_GCIP_TENANT_ID": tenant}
        with patch.dict(os.environ, env):
            registry = ConnectionRegistry.from_env()
            owner = registry.assigned(Principal(issuer, "existing-owner", tenant, ("mcp:access",)))
            first = registry.assigned(Principal(issuer, "new-user-1", tenant, ("mcp:access",)))
            second = registry.assigned(Principal(issuer, "new-user-2", tenant, ("mcp:access",)))
            foreign = registry.assigned(Principal(issuer, "foreign-user", "other-tenant", ("mcp:access",)))
        self.assertEqual(len(owner), 1)
        self.assertEqual(owner[0].id, template["id"])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].subjects, ("new-user-1",))
        self.assertEqual(first[0].credential_ref, first[0].id)
        self.assertIsNone(first[0].downstream_account_id)
        self.assertEqual(first[0].tools, tuple(template["tools"]))
        self.assertEqual(first[0].resources, tuple(template["resources"]))
        self.assertNotEqual(first[0].credential_ref, second[0].credential_ref)
        self.assertEqual(foreign, [])

    def test_tenant_self_service_fails_closed_without_gcips_tenant_mode(self):
        from .gateway.connections import ConnectionRegistry
        template = {"id": "template", "remote": "ditra-analytics", "mode": "delegated",
            "tenant": "tenant", "issuer": "https://securetoken.google.com/project", "subjects": ["owner"],
            "credential_ref": "owner-grant", "tools": ["search"]}
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([template]),
                "LOTTOMATICAPSS_GATEWAY_DITRA_SELF_SERVICE": "true",
                "LOTTOMATICAPSS_MCP_AUTH_MODE": "oidc_proxy"}):
            with self.assertRaisesRegex(ValueError, "requires GCIP tenant access mode"):
                ConnectionRegistry.from_env()

    def test_stateless_http_partition_is_stable_and_session_headers_remain_isolated(self):
        from types import SimpleNamespace
        from .gateway import connections
        principal = connections.Principal("https://issuer", "uid", "tenant")
        middleware = connections.ConnectionPolicyMiddleware([])
        request = SimpleNamespace(headers={})
        with patch.object(connections, "get_http_request", return_value=request), \
                patch.object(connections, "get_access_token", return_value=SimpleNamespace(client_id="client")):
            with middleware.scope(principal, {}):
                first = connections.session_partition()
            with middleware.scope(principal, {}):
                self.assertEqual(connections.session_partition(), first)
            request.headers["mcp-session-id"] = "session-1"
            with middleware.scope(principal, {}):
                session = connections.session_partition()
                self.assertNotEqual(session, first)
            with middleware.scope(connections.Principal("https://issuer", "other", "tenant"), {}):
                self.assertNotEqual(connections.session_partition(), session)

    def test_middleware_denies_anonymous_foreign_users_and_remote_dispatch_bypass(self):
        from types import SimpleNamespace
        from .gateway import connections
        from fastmcp.server.auth.auth import AccessToken

        record = {"id": "personal", "remote": "ditra-analytics", "mode": "delegated",
                  "tenant": "tenant", "issuer": "https://issuer", "subjects": ["uid"],
                  "credential_ref": "grant", "tools": ["search"],
                  "required_scopes": ["analytics:read"]}
        token = AccessToken(token="test", client_id="client", subject="uid",
                            scopes=["analytics:read"], claims={"iss": "https://issuer", "firebase": {"tenant": "tenant"}})
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record])}):
            middleware = connections.ConnectionPolicyMiddleware([])
            executed = []

            async def next_call(context):
                executed.append(connections.current_connection("ditra-analytics").id)
                return "ok"

            async def scenario():
                context = SimpleNamespace(message=SimpleNamespace(name="search", arguments={}))
                with patch.object(connections, "get_access_token", return_value=token):
                    self.assertEqual(await middleware.on_call_tool(context, next_call), "ok")
                    dispatch = SimpleNamespace(message=SimpleNamespace(name="gateway_call_remote_tool",
                        arguments={"remote_name": "ditra-analytics", "tool_name": "execute_sql", "force_remote": True}))
                    with self.assertRaises(PermissionError):
                        await middleware.on_call_tool(dispatch, next_call)
                    echarts_tool = SimpleNamespace(message=SimpleNamespace(name="visualize_card_echarts", arguments={}))
                    with self.assertRaises(PermissionError):
                        await middleware.on_call_tool(echarts_tool, next_call)
                    resource = SimpleNamespace(message=SimpleNamespace(uri="ditra-analytics://dashboard-summary"))
                    with self.assertRaises(PermissionError):
                        await middleware.on_read_resource(resource, next_call)
                    echarts_resource = SimpleNamespace(message=SimpleNamespace(
                        uri="ui://ditra_analytics/metabase/echarts-saved-card.html"))
                    with self.assertRaises(PermissionError):
                        await middleware.on_read_resource(echarts_resource, next_call)
                for identity in (None, token.model_copy(update={"subject": "other"}),
                                 token.model_copy(update={"scopes": []}),
                                 token.model_copy(update={"claims": {"iss": "https://issuer", "tenant_id": "other"}})):
                    with patch.object(connections, "get_access_token", return_value=identity):
                        with self.assertRaises(PermissionError):
                            await middleware.on_call_tool(context, next_call)

            asyncio.run(scenario())
        self.assertEqual(executed, ["personal"])

    def test_separated_server_enforces_policy_through_real_tool_calls(self):
        from cryptography.fernet import Fernet
        from .gateway import connections
        from .metabase_client import MetabaseResult
        from fastmcp.server.auth.auth import AccessToken
        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

        record = {"id": "personal", "remote": "ditra-analytics", "mode": "delegated",
                  "tenant": "tenant", "issuer": "https://issuer", "subjects": ["uid"],
                  "credential_ref": "grant", "tools": ["search", "visualize_card"]}
        token = AccessToken(token="test", client_id="client", subject="uid", scopes=[],
                            claims={"iss": "https://issuer", "firebase": {"tenant": "tenant"}})
        env = {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record]),
               "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_ENCRYPTION_KEY": Fernet.generate_key().decode(),
               "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_STORE_PATH": "/tmp/test-only-unused-connections",
               "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "[]", "LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED": "false"}
        from . import server
        from .metabase_client import MetabaseClient

        async def search(_client, *args, **kwargs):
            self.assertEqual(connections.current_connection("ditra-analytics").id, "personal")
            return MetabaseResult({"data": []}, "mcp")

        async def get_card(_client, card_id):
            self.assertEqual(connections.current_connection("ditra-analytics").id, "personal")
            return MetabaseResult({"id": card_id, "display": "combo",
                                  "dataset_query": {"database": 2, "type": "query"}}, "mcp")

        async def visualize(*args, **kwargs):
            from mcp import types as mt
            self.assertEqual(connections.current_connection("ditra-analytics").id, "personal")
            return mt.CallToolResult(content=[], structuredContent={"query": "test"})

        async def run_card_query(_client, card_id, **kwargs):
            self.assertEqual(connections.current_connection("ditra-analytics").id, "personal")
            return MetabaseResult({"data": {"cols": [{"name": "count"}], "rows": [[22]]}}, "api")

        async def scenario():
            async with Client(create_mcp()) as client:
                tools = {tool.name: tool for tool in (await client.list_tools_mcp()).tools}
                self.assertEqual(tools["visualize_card"].meta["ui"]["resourceUri"], UI_URI)
                self.assertEqual(tools["visualize_card"].meta["openai/outputTemplate"], UI_URI)
                allowed = await client.call_tool_mcp("search", {"query": "orders"})
                denied = await client.call_tool_mcp("api_search", {"query": "orders"})
                native = await client.call_tool_mcp("visualize_card", {"card_id": 936})
                self.assertFalse(native.is_error)
                self.assertEqual(native.meta["lottomaticapss/rendering"]["renderer"], "native-mcp")
                with patch.object(server.native_viewer, "enabled", return_value=True):
                    saved = await client.call_tool_mcp("visualize_card", {"card_id": 936})
                self.assertFalse(saved.is_error)
                self.assertEqual(saved.structured_content["saved_visualization"]["display"], "combo")
                self.assertEqual(saved.structured_content["saved_visualization"]["version"], 1)
                self.assertTrue(saved.meta["lottomaticapss/rendering"]["saved_settings_preserved"])
                self.assertFalse(saved.meta["lottomaticapss/rendering"]["browser_rendering_verified"])
                table = await client.call_tool_mcp("visualize_card", {"card_id": 936, "output": "table"})
                self.assertFalse(table.is_error)
                self.assertEqual(table.structured_content["rows"], [[22]])
                self.assertEqual(table.meta["lottomaticapss/rendering"]["renderer"], "table")
                for tool in ("saved_card_embed_url", "visualize_card_echarts"):
                    blocked = await client.call_tool_mcp(tool, {"card_id": 936})
                    self.assertTrue(blocked.is_error)
                return allowed, denied

        with patch.dict(os.environ, env), \
                patch.object(server, "create_auth_provider", return_value=StaticTokenVerifier(tokens={})), \
                patch.object(connections, "get_access_token", return_value=token), \
                patch.object(MetabaseClient, "search", search), \
                patch.object(MetabaseClient, "get_card", get_card), \
                patch.object(MetabaseClient, "api_get_card", get_card), \
                patch.object(MetabaseClient, "api_run_card_query", run_card_query), \
                patch.object(server, "construct_and_visualize_remote_query", visualize):
            allowed, denied = asyncio.run(scenario())
        self.assertFalse(allowed.is_error)
        self.assertTrue(denied.is_error)

    def test_personal_status_never_exposes_credentials_or_other_users(self):
        from .gateway import connections
        principal = connections.Principal("https://issuer", "uid", "tenant")
        record = {"id": "mine", "remote": "ditra-analytics", "mode": "delegated",
                  "tenant": "tenant", "issuer": "https://issuer", "subjects": ["uid"],
                  "credential_ref": "my-grant", "tools": ["search"]}
        other = {**record, "id": "other", "subjects": ["other"], "credential_ref": "other-grant"}
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record, other])}), \
                patch.object(connections, "verified_principal", return_value=principal), \
                patch.object(remote_auth, "_load_runtime_remote_secrets", return_value={
                    "connection:my-grant": {"ACCESS_TOKEN": "secret-token", "ACCOUNT_EMAIL": "ditraadmin@example.com"}}):
            status = connections.integration_status()
        self.assertEqual(status["connections"], [{"id": "mine", "integration": "ditra-analytics",
                                                 "mode": "delegated", "state": "Configured",
                                                 "account_email": "ditraadmin@example.com"}])
        self.assertNotIn("secret-token", json.dumps(status))

    def test_missing_personal_grant_points_to_self_service_connect(self):
        from .gateway import connections
        principal = connections.Principal("https://issuer", "uid", "tenant")
        record = {"id": "mine", "remote": "ditra-analytics", "mode": "delegated", "tenant": "tenant",
                  "issuer": "https://issuer", "subjects": ["uid"], "credential_ref": "grant", "tools": ["search"]}
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record]),
                                    "LOTTOMATICAPSS_MCP_AUTH_MODE": "gcip"}), \
                patch.object(connections, "verified_principal", return_value=principal), \
                patch.object(remote_auth, "_load_runtime_remote_secrets", return_value={}):
            result = connections.integration_status()
        self.assertEqual(result["connections"][0]["next_action"], {
            "tool": "connect_integration", "arguments": {"connection_id": "mine"}})
        self.assertEqual(result["connections"][0]["state"], "Connection Required")

    def test_existing_status_tool_returns_setup_url_when_connect_tool_catalog_is_stale(self):
        from .gateway import connections
        from . import server
        from .artifacts.tools import local
        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

        principal = connections.Principal("https://issuer", "uid", "tenant")
        record = {"id": "mine", "remote": "ditra-analytics", "mode": "delegated", "tenant": "tenant",
                  "issuer": "https://issuer", "subjects": ["uid"], "credential_ref": "grant", "tools": ["search"]}
        class Setup:
            async def ticket(self, owner, connection_id):
                self_owner = (owner, connection_id)
                if self_owner != (principal, "mine"):
                    raise AssertionError("Wrong setup owner")
                return {"setup_url": "https://master.example.test/connections/start?ticket=opaque",
                        "expires_in": 300}
        async def scenario():
            async with Client(create_mcp()) as client:
                return await client.call_tool_mcp("list_integration_connections", {})
        env = {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record]),
               "LOTTOMATICAPSS_MCP_AUTH_MODE": "gcip",
               "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_ENCRYPTION_KEY": "test-not-used",
               "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_STORE_PATH": "/tmp/test-not-used"}
        with patch.dict(os.environ, env), \
                patch.object(server, "create_auth_provider", return_value=StaticTokenVerifier(tokens={})), \
                patch.object(server, "register_ditra_account_oauth", return_value=Setup()), \
                patch.object(connections, "verified_principal", return_value=principal), \
                patch.object(remote_auth, "_load_runtime_remote_secrets", return_value={}):
            result = asyncio.run(scenario())
        self.assertFalse(result.is_error)
        item = result.structured_content["connections"][0]
        self.assertTrue(item["setup_url"].startswith("https://master.example.test/connections/start?"))
        self.assertEqual(item["setup_expires_in"], 300)

    def test_connection_owner_tenant_and_tool_are_explicit(self):
        from .gateway.connections import ConnectionRegistry, IntegrationConnection, Principal, connection_scope, current_connection

        principal = Principal("https://issuer", "uid-1", "tenant-1")
        connection = IntegrationConnection(id="personal", remote="ditra-analytics", mode="delegated",
            tenant="tenant-1", issuer="https://issuer", subjects=("uid-1",), credential_ref="grant-1",
            tools=("search",), resources=("ditra-analytics://dashboard-summary",))
        registry = ConnectionRegistry([connection])
        self.assertEqual(registry.authorize(principal, "ditra-analytics", tool="search"), connection)
        for other in (Principal("https://issuer", "uid-2", "tenant-1"),
                      Principal("https://issuer", "uid-1", "tenant-2"),
                      Principal("https://other", "uid-1", "tenant-1")):
            with self.subTest(other=other), self.assertRaises(PermissionError):
                registry.authorize(other, "ditra-analytics", tool="search")
        with self.assertRaises(PermissionError):
            registry.authorize(principal, "ditra-analytics", tool="execute_sql")
        with self.assertRaises(PermissionError):
            registry.authorize(principal, "sharepoint", tool="search")
        with connection_scope(principal, {"ditra-analytics": connection}):
            self.assertEqual(current_connection("ditra-analytics"), connection)
        self.assertIsNone(current_connection("ditra-analytics"))

    def test_delegated_grants_cannot_be_shared_between_users(self):
        from .gateway.connections import ConnectionRegistry, IntegrationConnection

        first = IntegrationConnection(id="one", remote="ditra-analytics", mode="delegated",
            tenant="tenant", issuer="https://issuer", subjects=("uid-1",), credential_ref="grant",
            tools=("search",))
        second = first.model_copy(update={"id": "two", "subjects": ("uid-2",)})
        with self.assertRaises(ValueError):
            ConnectionRegistry([first, second])
        with self.assertRaises(ValueError):
            IntegrationConnection.model_validate({**first.model_dump(), "subjects": ["uid-1", "uid-2"]})

    def test_connection_credentials_are_encrypted_and_do_not_fall_back_to_global_auth(self):
        from cryptography.fernet import Fernet
        from .gateway.connections import IntegrationConnection, Principal, connection_scope
        from .metabase_client import MetabaseClient
        from .settings import MetabaseSettings

        connection = IntegrationConnection(id="personal", remote="ditra-analytics", mode="delegated",
            tenant="tenant", issuer="https://issuer", subjects=("uid",), credential_ref="personal-grant",
            tools=("search",))
        principal = Principal("https://issuer", "uid", "tenant")
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url="https://analytics.example/mcp", auth="global-token")
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "credentials.enc"
            key = Fernet.generate_key().decode()
            env = {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": "[]",
                   "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_STORE_PATH": str(store),
                   "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_ENCRYPTION_KEY": key,
                   "LOTTOMATICAPSS_GATEWAY_REMOTE_DITRA_ANALYTICS_ACCESS_TOKEN": "global-token"}
            with patch.dict(os.environ, env), patch.object(remote_auth, "_RUNTIME_REMOTE_SECRETS", None):
                with connection_scope(principal, {"ditra-analytics": connection}, "conversation-1"):
                    self.assertIsNone(remote_auth._get_remote_env(remote, "ACCESS_TOKEN"))
                    self.assertIsNone(remote_auth._get_explicit_remote_auth(remote))
                    with self.assertRaises(remote_auth.GatewayAuthConfigurationError):
                        asyncio.run(remote_auth.resolve_remote_auth(remote))
                    remote_auth.set_runtime_remote_credentials(remote, {"ACCESS_TOKEN": "personal-token"})
                    self.assertNotIn(b"personal-token", store.read_bytes())
                    self.assertEqual(store.stat().st_mode & 0o777, 0o600)
                    remote_auth._RUNTIME_REMOTE_SECRETS = None
                    client = MetabaseClient(MetabaseSettings(api_key="global-api-key"))
                    self.assertEqual(asyncio.run(client._auth_headers()), {"Authorization": "Bearer personal-token"})
                    first_key = proxy._remote_client_key(remote.name, remote.url)
                with connection_scope(principal, {"ditra-analytics": connection}, "conversation-2"):
                    self.assertNotEqual(proxy._remote_client_key(remote.name, remote.url), first_key)
                with self.assertRaises(PermissionError):
                    asyncio.run(client._auth_headers())

    def test_connection_mode_does_not_allow_no_auth_startup(self):
        env = {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": "[]",
               "LOTTOMATICAPSS_MCP_AUTH_MODE": "none"}
        with patch.dict(os.environ, env), self.assertRaisesRegex(ValueError, "master authentication"):
            create_mcp()


class DitraAccountOAuthTests(unittest.TestCase):
    def test_tenant_self_service_issues_connect_challenge_for_unassigned_gcipsubject(self):
        from types import SimpleNamespace
        from key_value.aio.stores.memory import MemoryStore
        from .gateway import connection_oauth
        from .gateway.connection_oauth import DitraAccountOAuth
        from .gateway.connections import Principal
        issuer = "https://securetoken.google.com/project"
        template = {"id": "existing-owner", "remote": "ditra-analytics", "mode": "delegated",
            "tenant": "tenant", "issuer": issuer, "subjects": ["owner"], "credential_ref": "owner-grant",
            "tools": ["search"], "required_scopes": ["mcp:access"]}
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
            type="streamable-http", url="https://analytics.example/api/metabase-mcp")
        manager = DitraAccountOAuth(SimpleNamespace(_client_storage=MemoryStore(),
            base_url="https://master.example.test"), [remote])
        env = {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([template]),
            "LOTTOMATICAPSS_GATEWAY_DITRA_SELF_SERVICE": "true",
            "LOTTOMATICAPSS_MCP_AUTH_MODE": "gcip", "LOTTOMATICAPSS_GCIP_ACCESS_MODE": "tenant",
            "LOTTOMATICAPSS_GCIP_PROJECT_ID": "project", "LOTTOMATICAPSS_GCIP_TENANT_ID": "tenant"}
        with patch.dict(os.environ, env), patch.object(connection_oauth, "_load_runtime_remote_secrets", return_value={}):
            result = asyncio.run(manager.ticket(Principal(issuer, "new-user", "tenant", ("mcp:access",))))
        self.assertTrue(result["setup_required"])
        self.assertTrue(result["setup_url"].startswith("https://master.example.test/connections/start?"))
        self.assertIn("mb:full", result["requested_scopes"])

    def test_configured_connection_does_not_create_another_authorization_request(self):
        from types import SimpleNamespace
        from key_value.aio.stores.memory import MemoryStore
        from .gateway import connection_oauth
        from .gateway.connections import Principal

        auth = SimpleNamespace(_client_storage=MemoryStore(), base_url="https://master.example.test")
        manager = connection_oauth.DitraAccountOAuth(auth, [])
        record = {"id": "mine", "remote": "ditra-analytics", "mode": "delegated", "tenant": "tenant",
                  "issuer": "https://issuer", "subjects": ["uid"], "credential_ref": "grant", "tools": ["search"]}
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record])}), \
                patch.object(connection_oauth, "_load_runtime_remote_secrets", return_value={
                    "connection:grant": {"REFRESH_TOKEN": "private-grant"}}):
            result = asyncio.run(manager.ticket(Principal("https://issuer", "uid", "tenant")))
        self.assertEqual(result["state"], "Configured")
        self.assertFalse(result["setup_required"])
        self.assertNotIn("setup_url", result)
        self.assertNotIn("private-grant", json.dumps(result))

    def test_configured_account_can_request_verified_downstream_account_switch(self):
        from types import SimpleNamespace
        from key_value.aio.stores.memory import MemoryStore
        from .gateway import connection_oauth
        from .gateway.connections import Principal
        from .settings import RemoteBackendSettings

        principal = Principal("https://issuer", "uid", "tenant")
        record = {"id": "ditra-user-uid", "remote": "ditra-analytics", "mode": "delegated",
                  "tenant": "tenant", "issuer": "https://issuer", "subjects": ["uid"],
                  "credential_ref": "ditra-user-uid", "tools": ["list_dashboard_cards"]}
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
            type="streamable-http", url="https://analytics.example/api/metabase-mcp")
        manager = connection_oauth.DitraAccountOAuth(SimpleNamespace(
            _client_storage=MemoryStore(), base_url="https://master.example.test"), [remote])
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record])}), \
                patch.object(connection_oauth, "_load_runtime_remote_secrets", return_value={
                    "connection:ditra-user-uid": {"REFRESH_TOKEN": "old-grant", "ACCOUNT_ID": "42",
                                                   "ACCOUNT_EMAIL": "old@example.com"}}):
            result = asyncio.run(manager.ticket(principal, account_email="new@example.com"))
        self.assertTrue(result["setup_required"])
        self.assertEqual(result["target_account_email"], "new@example.com")
        self.assertIn("new@example.com", result["message"])
        self.assertIn("setup_url", result)

    def test_personal_callback_checks_browser_and_rest_before_saving(self):
        from types import SimpleNamespace
        from key_value.aio.stores.memory import MemoryStore
        from fastmcp.server.auth.auth import AccessToken
        from .gateway import connection_oauth
        from .gateway.connections import Principal

        identity = AccessToken(token="signed-master", client_id="master", subject="uid", scopes=["mcp:access"],
                               claims={"iss": "https://issuer", "firebase": {"tenant": "tenant"}})
        async def browser_identity(request):
            return identity
        auth = SimpleNamespace(_client_storage=MemoryStore(), base_url="https://master.example.test",
                               browser_identity=browser_identity)
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url="https://analytics.example/api/metabase-mcp")
        manager = connection_oauth.DitraAccountOAuth(auth, [remote])
        record = {"id": "mine", "remote": "ditra-analytics", "mode": "delegated", "tenant": "tenant",
                  "issuer": "https://issuer", "subjects": ["uid"], "credential_ref": "personal",
                  "tools": ["list_dashboard_cards"]}
        calls = []
        saved = []
        reject_dashboard = False
        def handler(request):
            calls.append(request.url.path)
            if request.url.path == "/oauth/token":
                return httpx.Response(200, json={"access_token": "personal-token", "refresh_token": "personal-refresh",
                                                "scope": "mb:full agent:resource:read"})
            if request.url.path == "/api/user/current":
                return httpx.Response(200, json={"id": 42})
            if request.url.path == "/api/dashboard/30":
                return httpx.Response(403 if reject_dashboard else 200, json={"id": 30})
            if request.url.path == "/oauth/revoke":
                self.assertEqual(parse_qs(request.content.decode())["token"], ["personal-refresh"])
                return httpx.Response(200)
            raise AssertionError(request.url.path)
        async_client = httpx.AsyncClient
        def client(**kwargs):
            return async_client(transport=httpx.MockTransport(handler), **kwargs)
        async def scenario():
            async def seed():
                await manager.storage.put(key=manager.key("state"), collection="integration-oauth", ttl=600,
                value={"owner": ["https://issuer", "uid", "tenant"], "connection_id": "mine",
                       "binding": manager.key("binding"), "origin": "https://analytics.example",
                       "token_endpoint": "https://analytics.example/oauth/token", "expires": time.time()+600,
                       "client_id": "cid", "client_secret": "test-secret", "verifier": "verifier",
                       "scopes": ["mb:full", "agent:resource:read"], "issuer": "https://analytics.example",
                       "issuer_required": True, "revocation_endpoint": "https://analytics.example/oauth/revoke"})
            await seed()
            from starlette.requests import Request
            def request(cookie, query=b"state=state&code=code&iss=https%3A%2F%2Fanalytics.example"):
                return Request({"type": "http", "method": "GET", "path": "/connections/callback",
                    "query_string": query, "headers": [(b"cookie", cookie.encode())]})
            for query in (b"state=state&code=code", b"state=state&code=code&iss=https%3A%2F%2Fevil.example"):
                invalid_issuer = await manager.callback(request("__Host-integration-oauth=binding", query))
                self.assertEqual(invalid_issuer.status_code, 403)
                self.assertEqual(calls, [])
            denied = await manager.callback(request("__Host-integration-oauth=incorrect"))
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(calls, [])
            allowed = await manager.callback(request("__Host-integration-oauth=binding"))
            self.assertEqual(allowed.status_code, 200)
            replay = await manager.callback(request("__Host-integration-oauth=binding"))
            self.assertEqual(replay.status_code, 400)
            await seed()
            nonlocal reject_dashboard
            reject_dashboard = True
            failed = await manager.callback(request("__Host-integration-oauth=binding"))
            self.assertEqual(failed.status_code, 403)
        async def save(remote, credentials, **kwargs):
            saved.append(credentials)
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record])}), \
                patch.object(connection_oauth.httpx, "AsyncClient", client), \
                patch.object(connection_oauth, "_get_remote_env", return_value=None), \
                patch.object(connection_oauth, "set_runtime_remote_credentials_async", save):
            asyncio.run(scenario())
        self.assertEqual(calls, ["/oauth/token", "/api/user/current", "/api/dashboard/30",
                     "/oauth/token", "/api/user/current", "/api/dashboard/30", "/oauth/revoke"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["ACCOUNT_ID"], "42")
        self.assertIn("mb:full", saved[0]["SCOPE"])
        self.assertNotIn("ACCESS_TOKEN", saved[0])

    def test_explicit_account_switch_verifies_email_and_preserves_old_grant_on_mismatch(self):
        from types import SimpleNamespace
        from key_value.aio.stores.memory import MemoryStore
        from .gateway import connection_oauth
        from .gateway.connections import Principal

        principal = Principal("https://issuer", "uid", "tenant", ("mcp:access",))
        record = {"id": "ditra-user-uid", "remote": "ditra-analytics", "mode": "delegated",
            "tenant": "tenant", "issuer": "https://issuer", "subjects": ["uid"],
            "credential_ref": "ditra-user-uid", "tools": ["list_dashboard_cards"]}
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
            type="streamable-http", url="https://analytics.example/api/metabase-mcp")
        old_grant = {"ACCOUNT_ID": "42", "ACCOUNT_EMAIL": "old@example.com", "REFRESH_TOKEN": "old-refresh",
                     "CLIENT_ID": "old-client", "CLIENT_SECRET": "old-secret"}
        async_client = httpx.AsyncClient

        async def attempt(current_email):
            manager = connection_oauth.DitraAccountOAuth(SimpleNamespace(
                _client_storage=MemoryStore(), base_url="https://master.example.test"), [remote])
            calls = []
            saved = []
            async def browser_owner(request, record):
                return principal
            async def save(remote, credentials, *, allow_account_change=False):
                saved.append((credentials, allow_account_change))
            def handler(request):
                calls.append(request.url.path)
                if request.url.path == "/oauth/token":
                    return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh",
                        "scope": "mb:full agent:resource:read"})
                if request.url.path == "/api/user/current":
                    return httpx.Response(200, json={"id": 43, "email": current_email})
                if request.url.path == "/api/dashboard/30":
                    return httpx.Response(200, json={"id": 30})
                if request.url.path == "/oauth/revoke":
                    calls.append("revoke:" + parse_qs(request.content.decode())["token"][0])
                    return httpx.Response(200)
                raise AssertionError(request.url.path)
            def client(**kwargs):
                return async_client(transport=httpx.MockTransport(handler), **kwargs)
            await manager.storage.put(key=manager.key("state"), collection="integration-oauth", ttl=600,
                value={"owner": [principal.issuer, principal.subject, principal.tenant],
                    "connection_id": "ditra-user-uid", "binding": manager.key("binding"),
                    "origin": "https://analytics.example", "token_endpoint": "https://analytics.example/oauth/token",
                    "expires": time.time()+600, "client_id": "new-client", "client_secret": "new-secret",
                    "verifier": "verifier", "scopes": ["mb:full", "agent:resource:read"],
                    "issuer": "https://analytics.example", "issuer_required": False,
                    "revocation_endpoint": "https://analytics.example/oauth/revoke",
                    "target_account_email": "new@example.com"})
            from starlette.requests import Request
            request=Request({"type":"http","method":"GET","path":"/connections/callback",
                "query_string":b"state=state&code=code",
                "headers":[(b"cookie",b"__Host-integration-oauth=binding")]})
            with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([record])}), \
                    patch.object(connection_oauth.httpx,"AsyncClient",client), \
                    patch.object(connection_oauth,"_load_runtime_remote_secrets",return_value={"connection:ditra-user-uid":old_grant}), \
                    patch.object(connection_oauth,"_get_remote_env",return_value="42"), \
                    patch.object(connection_oauth,"set_runtime_remote_credentials_async",save), \
                    patch.object(manager,"browser_owner",browser_owner):
                response=await manager.callback(request)
            return response.status_code, saved, calls

        async def scenario():
            mismatch=await attempt("old@example.com")
            matched=await attempt("new@example.com")
            return mismatch,matched
        mismatch,matched=asyncio.run(scenario())
        self.assertEqual(mismatch[0],403)
        self.assertEqual(mismatch[1],[])
        self.assertIn("revoke:new-refresh", mismatch[2])
        self.assertEqual(matched[0],200)
        self.assertEqual(matched[1][0][0]["ACCOUNT_ID"],"43")
        self.assertEqual(matched[1][0][0]["ACCOUNT_EMAIL"],"new@example.com")
        self.assertTrue(matched[1][0][1])
        self.assertIn("revoke:old-refresh", matched[2])

    def test_unauthorized_browser_cannot_start_personal_oauth(self):
        from types import SimpleNamespace
        from key_value.aio.stores.memory import MemoryStore
        from .gateway.connection_oauth import DitraAccountOAuth
        async def absent(request):
            return None
        manager = DitraAccountOAuth(SimpleNamespace(_client_storage=MemoryStore(),
            base_url="https://master.example.test", browser_identity=absent), [])
        async def scenario():
            await manager.storage.put(key=manager.key("ticket"), collection="integration-tickets", ttl=300,
                value={"owner": ["https://issuer", "uid", "tenant"]})
            request = SimpleNamespace(query_params={"ticket": "ticket"})
            response = await manager.start(request)
            self.assertEqual(response.status_code, 403)
        asyncio.run(scenario())

    def test_setup_ticket_is_owner_bound_and_explicitly_requests_full_api_scope(self):
        from types import SimpleNamespace
        from key_value.aio.stores.memory import MemoryStore
        from .gateway.connection_oauth import DitraAccountOAuth
        from .gateway.connections import Principal

        auth = SimpleNamespace(_client_storage=MemoryStore(), base_url="https://master.example.test")
        remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                       type="streamable-http", url="https://analytics.example/api/metabase-mcp")
        manager = DitraAccountOAuth(auth, [remote])
        connection = {"id": "mine", "remote": "ditra-analytics", "mode": "delegated", "tenant": "tenant",
                      "issuer": "https://issuer", "subjects": ["uid"], "credential_ref": "personal",
                      "tools": ["list_dashboard_cards"]}
        principal = Principal("https://issuer", "uid", "tenant")
        with patch.dict(os.environ, {"LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": json.dumps([connection])}):
            ticket = asyncio.run(manager.ticket(principal))
            self.assertIn("mb:full", ticket["requested_scopes"])
            self.assertEqual(ticket["expires_in"], 300)
            self.assertNotIn("uid", ticket["setup_url"])
            with self.assertRaises(PermissionError):
                asyncio.run(manager.ticket(Principal("https://issuer", "other", "tenant")))


class GCIPVerifierTests(unittest.TestCase):
    def bridge(self):
        from key_value.aio.stores.memory import MemoryStore
        from .gcip_auth import GCIPOAuthBridge
        return GCIPOAuthBridge(project_id="project", tenant_id="tenant", api_key="public-test-api-key",
            auth_domain="project.firebaseapp.com", client_id="test-client", signing_key="test-only-signing-key-at-least-32-characters",
            subjects=("uid",), base_url="https://master.example.test",
            allowed_client_redirect_uris=["https://client.example.test/callback"], client_storage=MemoryStore())

    def request(self, path, *, body=b"", content_type="application/json", headers=None):
        from starlette.requests import Request
        sent = False
        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        values = {"content-type": content_type, **(headers or {})}
        return Request({"type": "http", "method": "POST", "path": path,
                        "scheme": "https", "server": ("master.example.test", 443), "query_string": b"",
                        "headers": [(name.encode(), value.encode()) for name, value in values.items()]}, receive)

    def test_auth_none_needs_no_gcip_configuration(self):
        from .oauth import create_auth_provider
        for mode in ("none", "off", "disabled"):
            with self.subTest(mode=mode), patch.dict(os.environ, {
                    "LOTTOMATICAPSS_MCP_AUTH_MODE": mode,
                    "LOTTOMATICAPSS_GCIP_PROJECT_ID": "",
                    "LOTTOMATICAPSS_GCIP_WEB_API_KEY": ""}):
                self.assertIsNone(create_auth_provider())

    def test_gcip_provider_accepts_claim_policy_without_uid_allowlist(self):
        from . import gcip_auth, oauth
        env = {
            "LOTTOMATICAPSS_MCP_AUTH_MODE": "gcip",
            "LOTTOMATICAPSS_GCIP_ACCESS_MODE": "claim",
            "LOTTOMATICAPSS_MCP_BASE_URL": "https://master.example.test",
            "LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": "[]",
            "LOTTOMATICAPSS_GCIP_PROJECT_ID": "project",
            "LOTTOMATICAPSS_GCIP_TENANT_ID": "tenant",
            "LOTTOMATICAPSS_GCIP_WEB_API_KEY": "test-api-key",
            "LOTTOMATICAPSS_GCIP_AUTH_DOMAIN": "project.firebaseapp.com",
            "LOTTOMATICAPSS_GCIP_CLIENT_ID": "test-client",
            "LOTTOMATICAPSS_GCIP_SIGNING_KEY": "test-signing-key-at-least-32-characters-long",
            "LOTTOMATICAPSS_GCIP_ALLOWED_SUBJECTS": "",
            "LOTTOMATICAPSS_GCIP_ACCESS_CLAIM": "mcp_access",
            "LOTTOMATICAPSS_GCIP_CLIENT_REDIRECT_URIS": "https://client.example.test/callback",
        }
        with patch.dict(os.environ, env), patch.object(gcip_auth, "GCIPOAuthBridge") as bridge:
            self.assertIs(oauth.create_auth_provider(), bridge.return_value)
        self.assertEqual(bridge.call_args.kwargs["subjects"], ())
        self.assertEqual(bridge.call_args.kwargs["access_claim"], "mcp_access")

    def test_gcip_requires_subjects_or_claim_policy(self):
        from .oauth import create_auth_provider
        env = {
            "LOTTOMATICAPSS_MCP_AUTH_MODE": "gcip",
            "LOTTOMATICAPSS_MCP_BASE_URL": "https://master.example.test",
            "LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": "[]",
            "LOTTOMATICAPSS_GCIP_ALLOWED_SUBJECTS": "",
            "LOTTOMATICAPSS_GCIP_ACCESS_CLAIM": "",
        }
        with patch.dict(os.environ, env), self.assertRaisesRegex(RuntimeError, "conflicting or missing policy settings"):
            create_auth_provider()

    def test_gcip_provider_tenant_mode_omits_uid_and_claim_policies(self):
        from . import gcip_auth, oauth
        env = {
            "LOTTOMATICAPSS_MCP_AUTH_MODE": "gcip",
            "LOTTOMATICAPSS_MCP_BASE_URL": "https://master.example.test",
            "LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON": "[]",
            "LOTTOMATICAPSS_GCIP_PROJECT_ID": "project",
            "LOTTOMATICAPSS_GCIP_TENANT_ID": "tenant",
            "LOTTOMATICAPSS_GCIP_WEB_API_KEY": "test-api-key",
            "LOTTOMATICAPSS_GCIP_AUTH_DOMAIN": "project.firebaseapp.com",
            "LOTTOMATICAPSS_GCIP_CLIENT_ID": "test-client",
            "LOTTOMATICAPSS_GCIP_SIGNING_KEY": "test-signing-key-at-least-32-characters-long",
            "LOTTOMATICAPSS_GCIP_ACCESS_MODE": "tenant",
            "LOTTOMATICAPSS_GCIP_ALLOWED_SUBJECTS": "",
            "LOTTOMATICAPSS_GCIP_ACCESS_CLAIM": "",
            "LOTTOMATICAPSS_GCIP_CLIENT_REDIRECT_URIS": "https://client.example.test/callback",
        }
        with patch.dict(os.environ, env), patch.object(gcip_auth, "GCIPOAuthBridge") as bridge:
            self.assertIs(oauth.create_auth_provider(), bridge.return_value)
        self.assertEqual(bridge.call_args.kwargs["subjects"], ())
        self.assertIsNone(bridge.call_args.kwargs["access_claim"])
        self.assertTrue(bridge.call_args.kwargs["allow_any_tenant_user"])

    def test_master_scope_defaults_to_explicit_gateway_access(self):
        bridge = self.bridge()
        self.assertEqual(bridge.required_scopes, ["mcp:access"])
        self.assertEqual(bridge.bridge_verifier.required_scopes, [])

    def test_oauth_discovery_agrees_on_exact_issuer_and_challenges_anonymous_requests(self):
        bridge = self.bridge()
        async def scenario():
            app = FastMCP("GCIP discovery test", auth=bridge).http_app(path="/mcp")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="https://master.example.test") as client:
                authorization = (await client.get("/.well-known/oauth-authorization-server")).json()
                resource = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
                self.assertIn(authorization["issuer"], resource["authorization_servers"])
                self.assertIn("S256", authorization["code_challenge_methods_supported"])
                self.assertIn("mcp:access", authorization["scopes_supported"])
                self.assertTrue(authorization["authorization_response_iss_parameter_supported"])
                response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
                self.assertEqual(response.status_code, 401)
                self.assertIn("resource_metadata", response.headers["www-authenticate"])
        asyncio.run(scenario())

    def test_browser_handoff_requires_origin_and_binding(self):
        bridge = self.bridge()
        data = json.dumps({"state": "state", "csrf": "csrf", "id_token": "id-token", "refresh_token": "refresh"}).encode()
        async def scenario():
            cross_origin = await bridge.complete_login(self.request("/gcip/complete", body=data,
                headers={"origin": "https://attacker.example.test"}))
            self.assertEqual(cross_origin.status_code, 403)
            missing_binding = await bridge.complete_login(self.request("/gcip/complete", body=data,
                headers={"origin": "https://master.example.test"}))
            self.assertEqual(missing_binding.status_code, 403)
        asyncio.run(scenario())

    def test_completed_login_is_bound_and_cannot_be_replayed(self):
        from fastmcp.server.auth.auth import AccessToken
        from types import SimpleNamespace
        bridge = self.bridge()
        identity = AccessToken(token="signed", client_id="project", subject="uid", scopes=["mcp:access"])
        async def verified(_token):
            return identity
        async def transaction(_state):
            return SimpleNamespace()
        body = json.dumps({"state": "state", "csrf": "csrf", "id_token": "signed", "refresh_token": "refresh"}).encode()
        async def scenario():
            await bridge._client_storage.put(key=bridge._key("state"), collection="gcip-login", ttl=300,
                value={"binding": bridge._key("binding"), "csrf": bridge._key("csrf"), "challenge": "challenge"})
            headers = {"origin": "https://master.example.test", "cookie": "__Host-gcip-login=binding"}
            with patch.object(bridge, "_transaction", transaction), \
                    patch.object(bridge.bridge_verifier, "verify_token", verified):
                success = await bridge.complete_login(self.request("/gcip/complete", body=body, headers=headers))
                replay = await bridge.complete_login(self.request("/gcip/complete", body=body, headers=headers))
            self.assertEqual(success.status_code, 200)
            self.assertEqual(replay.status_code, 403)
            target = json.loads(success.body)["redirect"]
            self.assertTrue(target.startswith("https://master.example.test/auth/callback?"))
            self.assertNotIn("signed", target)
            self.assertNotIn("refresh", target)
        asyncio.run(scenario())

    def test_browser_identity_requires_a_bound_verified_account(self):
        from fastmcp.server.auth.auth import AccessToken
        bridge = self.bridge()
        identity = AccessToken(token="signed", client_id="project", subject="uid", scopes=["mcp:access"])
        async def scenario():
            await bridge._client_storage.put(key=bridge._key("session"), collection="gcip-browser-identity", ttl=300,
                value={"id_token": "signed", "subject": "uid"})
            async def verified(_token):
                return identity
            with patch.object(bridge.bridge_verifier, "verify_token", verified):
                self.assertIsNone(await bridge.browser_identity(self.request("/connections/start")))
                result = await bridge.browser_identity(self.request("/connections/start",
                    headers={"cookie": "__Host-master-identity=session"}))
                self.assertEqual(result.subject, "uid")
            async def invalid(_token):
                return None
            with patch.object(bridge.bridge_verifier, "verify_token", invalid):
                self.assertIsNone(await bridge.browser_identity(self.request("/connections/start",
                    headers={"cookie": "__Host-master-identity=session"})))
        asyncio.run(scenario())

    def test_bridge_code_is_pkce_bound_and_single_use(self):
        bridge = self.bridge()
        verifier = "test-code-verifier"
        challenge = base64.urlsafe_b64encode(__import__("hashlib").sha256(verifier.encode()).digest()).decode().rstrip("=")
        async def refreshed(_refresh):
            return {"access_token": "verified-id-token", "refresh_token": "rotated-refresh",
                    "expires_in": 3600, "scope": "mcp:access", "token_type": "Bearer", "subject": "uid"}
        def request(code_verifier):
            from urllib.parse import urlencode
            return self.request("/gcip/token", content_type="application/x-www-form-urlencoded", body=urlencode({
                "grant_type": "authorization_code", "code": "code", "code_verifier": code_verifier,
                "client_id": "test-client", "client_secret": "test-only-signing-key-at-least-32-characters",
                "redirect_uri": "https://master.example.test/auth/callback"}).encode())
        async def scenario():
            await bridge._client_storage.put(key=bridge._key("code"), collection="gcip-codes", ttl=60,
                value={"id_token": "initial", "refresh_token": "refresh", "subject": "uid",
                       "challenge": challenge, "expires": time.time() + 60})
            with patch.object(bridge, "_refreshed_tokens", refreshed):
                denied = await bridge.token_exchange(request("incorrect"))
                allowed = await bridge.token_exchange(request(verifier))
                replay = await bridge.token_exchange(request(verifier))
            self.assertEqual(denied.status_code, 400)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(replay.status_code, 400)
            self.assertEqual(json.loads(allowed.body)["scope"], "mcp:access")
        asyncio.run(scenario())

    def test_refresh_and_client_authentication_fail_closed(self):
        bridge = self.bridge()
        async def scenario():
            from urllib.parse import urlencode
            invalid_client = await bridge.token_exchange(self.request("/gcip/token",
                content_type="application/x-www-form-urlencoded", body=urlencode({
                    "client_id": "test-client", "client_secret": "incorrect", "grant_type": "refresh_token"}).encode()))
            self.assertEqual(invalid_client.status_code, 401)
            async def revoked(_refresh):
                return None
            with patch.object(bridge, "_refreshed_tokens", revoked):
                denied = await bridge.token_exchange(self.request("/gcip/token",
                    content_type="application/x-www-form-urlencoded", body=urlencode({
                        "client_id": "test-client", "client_secret": "test-only-signing-key-at-least-32-characters",
                        "grant_type": "refresh_token", "refresh_token": "revoked"}).encode()))
            self.assertEqual(denied.status_code, 400)
        asyncio.run(scenario())

    def test_verified_gcip_tenant_and_subject_are_required(self):
        from fastmcp.server.auth.auth import AccessToken
        from fastmcp.server.auth.providers.jwt import JWTVerifier
        from .gcip_auth import GCIPTokenVerifier

        verifier = GCIPTokenVerifier("project", "tenant", ("uid",))
        identity = AccessToken(token="signed-token", client_id="project", subject="uid", scopes=[],
                               claims={"firebase": {"tenant": "tenant"}, "sub": "uid"})
        async def scenario():
            for token, permitted in ((identity, True), (None, False),
                                     (identity.model_copy(update={"subject": "other"}), False),
                                     (identity.model_copy(update={"claims": {"firebase": {"tenant": "other"}}}), False)):
                async def verified(_self, _raw):
                    return token
                with patch.object(JWTVerifier, "verify_token", verified):
                    result = await verifier.verify_token("signed-token")
                self.assertEqual(result is not None, permitted)
                if result:
                    self.assertEqual(result.scopes, ["mcp:access"])
        asyncio.run(scenario())

    def test_verified_gcip_tenant_mode_accepts_any_subject_only_in_configured_tenant(self):
        from fastmcp.server.auth.auth import AccessToken
        from fastmcp.server.auth.providers.jwt import JWTVerifier
        from .gcip_auth import GCIPTokenVerifier

        verifier = GCIPTokenVerifier("project", "tenant", allow_any_tenant_user=True)
        identities = (
            (AccessToken(token="signed", client_id="project", subject="uid-2", scopes=[],
                         claims={"firebase": {"tenant": "tenant"}}), True),
            (AccessToken(token="signed", client_id="project", subject="uid-3", scopes=[],
                         claims={"firebase": {"tenant": "other"}}), False),
        )
        async def scenario():
            for identity, permitted in identities:
                async def verified(_self, _raw, result=identity):
                    return result
                with patch.object(JWTVerifier, "verify_token", verified):
                    result = await verifier.verify_token("signed")
                self.assertEqual(result is not None, permitted)
        asyncio.run(scenario())

    def test_verified_gcip_access_claim_replaces_static_subject_allowlist(self):
        from fastmcp.server.auth.auth import AccessToken
        from fastmcp.server.auth.providers.jwt import JWTVerifier
        from .gcip_auth import GCIPTokenVerifier

        verifier = GCIPTokenVerifier("project", "tenant", access_claim="mcp_access")
        identities = (
            (AccessToken(token="signed", client_id="project", subject="uid", scopes=[],
                         claims={"firebase": {"tenant": "tenant"}, "mcp_access": True}), True),
            (AccessToken(token="signed", client_id="project", subject="uid", scopes=[],
                         claims={"firebase": {"tenant": "tenant"}, "mcp_access": False}), False),
            (AccessToken(token="signed", client_id="project", subject="uid", scopes=[],
                         claims={"firebase": {"tenant": "other"}, "mcp_access": True}), False),
        )
        async def scenario():
            for identity, permitted in identities:
                async def verified(_self, _raw, result=identity):
                    return result
                with patch.object(JWTVerifier, "verify_token", verified):
                    result = await verifier.verify_token("signed")
                self.assertEqual(result is not None, permitted)
        asyncio.run(scenario())

    def test_gcip_requires_exactly_one_subject_or_claim_policy(self):
        from .gcip_auth import GCIPTokenVerifier
        with self.assertRaisesRegex(ValueError, "exactly one access policy"):
            GCIPTokenVerifier("project", "tenant")
        with self.assertRaisesRegex(ValueError, "exactly one access policy"):
            GCIPTokenVerifier("project", "tenant", ("uid",), "mcp_access")


class DitraOIDCPilotTests(unittest.TestCase):
    def test_tenant_specific_oidc_configuration_preserves_safe_pilot_settings(self):
        from . import oauth

        env = {
            "LOTTOMATICAPSS_MCP_AUTH_MODE": "oidc_proxy",
            "LOTTOMATICAPSS_MCP_BASE_URL": "https://pilot.example.test",
            "LOTTOMATICAPSS_MCP_RESOURCE_BASE_URL": "",
            "LOTTOMATICAPSS_OIDC_CONFIG_URL": "https://login.microsoftonline.com/09150482-f0ba-4f90-b762-a639c1cb7a40/v2.0/.well-known/openid-configuration",
            "LOTTOMATICAPSS_OIDC_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
            "LOTTOMATICAPSS_OIDC_CLIENT_SECRET": "test-only-client-secret",
            "LOTTOMATICAPSS_OIDC_JWT_SIGNING_KEY": "test-only-pilot-signing-key",
            "LOTTOMATICAPSS_OIDC_REQUIRED_SCOPES": "openid profile email offline_access",
            "LOTTOMATICAPSS_OIDC_VERIFY_ID_TOKEN": "true",
            "LOTTOMATICAPSS_OIDC_FORWARD_RESOURCE": "false",
            "LOTTOMATICAPSS_OIDC_TOKEN_ENDPOINT_AUTH_METHOD": "client_secret_post",
            "LOTTOMATICAPSS_OIDC_ALLOWED_CLIENT_REDIRECT_URIS": "https://client.example.test/callback",
        }
        with patch.dict(os.environ, env), patch.object(oauth, "OIDCProxy") as provider:
            result = oauth.create_auth_provider()
        self.assertIs(result, provider.return_value)
        kwargs = provider.call_args.kwargs
        self.assertEqual(kwargs["config_url"], env["LOTTOMATICAPSS_OIDC_CONFIG_URL"])
        self.assertTrue(kwargs["verify_id_token"])
        self.assertFalse(kwargs["forward_resource"])
        self.assertEqual(kwargs["required_scopes"], ["openid", "profile", "email", "offline_access"])
        self.assertEqual(kwargs["token_endpoint_auth_method"], "client_secret_post")
        self.assertEqual(kwargs["allowed_client_redirect_uris"], ["https://client.example.test/callback"])
        self.assertEqual(kwargs["jwt_signing_key"], "test-only-pilot-signing-key")
        self.assertNotIn("require_authorization_consent", kwargs)

    def test_existing_oidc_resource_forwarding_default_is_unchanged(self):
        from .oauth import _env_bool

        with patch.dict(os.environ, {"LOTTOMATICAPSS_OIDC_FORWARD_RESOURCE": ""}):
            self.assertTrue(_env_bool("LOTTOMATICAPSS_OIDC_FORWARD_RESOURCE", True))


class BusinessGuidanceTests(unittest.TestCase):
    def test_skill_tool_manifest_and_server_instructions_are_available_without_downstream(self):
        env = {"LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED": "false",
               "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "[]",
               "LOTTOMATICAPSS_GATEWAY_ENABLE_TOOLBOX": "false",
               "LOTTOMATICAPSS_MCP_AUTH_MODE": "none"}

        async def scenario():
            async with Client(create_mcp()) as client:
                resources = (await client.list_resources_mcp()).resources
                skill = await client.read_resource_mcp("skill://lottomatica-pss/SKILL.md")
                manifest = await client.read_resource_mcp("skill://lottomatica-pss/_manifest")
                guidance = await client.call_tool_mcp("get_business_guidance", {})
                registry = await client.call_tool_mcp("registry_summary", {})
                tools = (await client.list_tools_mcp()).tools
                return client.instructions, resources, skill, manifest, guidance, registry, tools

        with patch.dict(os.environ, env):
            instructions, resources, skill, manifest, guidance, registry, tools = asyncio.run(scenario())
        self.assertIn("Lottomatica PSS MCP", instructions)
        self.assertIn("get_business_guidance", instructions)
        resource_uris = {str(resource.uri) for resource in resources}
        self.assertIn("skill://lottomatica-pss/SKILL.md", resource_uris)
        self.assertIn("skill://lottomatica-pss/_manifest", resource_uris)
        text = skill.contents[0].text
        self.assertEqual(guidance.content[0].text, text)
        self.assertIn("Ditra Analytics", text)
        self.assertNotIn("Metabase", text)
        self.assertIn("63.19.1", text)
        self.assertIn("SKILL.md", manifest.contents[0].text)
        self.assertIn("get_business_guidance", registry.structured_content["local"]["tools"]["names"])
        self.assertIn("skill://lottomatica-pss/SKILL.md", registry.structured_content["local"]["resources"])
        tool = next(item for item in tools if item.name == "get_business_guidance")
        self.assertTrue(tool.annotations.read_only_hint)


class RemoteBearerAuthTests(unittest.TestCase):
    remote = RemoteBackendSettings(name="ditra-analytics", namespace="ditra_analytics",
                                   type="streamable-http", url="https://analytics.example/mcp", auth="__auto__")

    def run_flow(self, statuses, tokens, refresh_configured=True):
        seen: list[str] = []

        def handler(request):
            seen.append(request.headers.get("authorization"))
            return httpx2.Response(statuses[len(seen) - 1])

        async def resolve(_remote):
            return tokens[0]

        async def force(_remote, *, rejected_token=None):
            self.assertEqual(rejected_token, tokens[0])
            return tokens[1]

        async def call():
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler),
                                          auth=RemoteBearerAuth(self.remote)) as client:
                return (await client.get("https://analytics.example/mcp")).status_code

        with patch.object(remote_auth, "resolve_remote_auth", resolve), \
                patch.object(remote_auth, "resolve_remote_auth_force_refresh", force), \
                patch.object(remote_auth, "is_refresh_flow_configured", lambda _r: refresh_configured):
            return asyncio.run(call()), seen

    def test_token_is_resolved_per_request_and_refreshed_once_on_401(self):
        status, seen = self.run_flow([401, 200], ["stale", "fresh"])
        self.assertEqual(status, 200)
        self.assertEqual(seen, ["Bearer stale", "Bearer fresh"])

    def test_no_retry_without_refresh_flow(self):
        status, seen = self.run_flow([401], ["static", "static"], refresh_configured=False)
        self.assertEqual(status, 401)
        self.assertEqual(seen, ["Bearer static"])

    def test_prefixed_static_token_is_not_double_prefixed(self):
        status, seen = self.run_flow([200], ["Bearer svc", "Bearer svc"], refresh_configured=False)
        self.assertEqual(seen, ["Bearer svc"])


if __name__ == "__main__":
    unittest.main()
