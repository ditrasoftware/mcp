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

import httpx2
import uvicorn
from fastmcp import Client, FastMCP
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
    def construct_query(query: dict, prompt: str = "") -> dict:
        return {"query_handle": "h-1"}

    @stub.tool(meta={"ui": {"resourceUri": "ui://metabase/visualize-query.html"}})
    def visualize_query(query_handle: str | None = None, query: dict | None = None) -> dict:
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
        self.mcp_app = _ditra_stub().http_app(path="/mcp")
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

    def test_local_preferred_routing_keeps_local_tools_local(self):
        local = {"answer_dashboard_kpi", "get_dashboard_card_data"}
        decision = _resolve_remote_route(route_policy="local_preferred", tool_name="get_dashboard_card_data",
                                         local_tool_names=local, tool_route_overrides={}, force_remote=False)
        self.assertEqual(decision["decision"], "local")
        remote = _resolve_remote_route(route_policy="local_preferred", tool_name="construct_query",
                                       local_tool_names=local, tool_route_overrides={}, force_remote=False)
        self.assertEqual(remote["decision"], "remote")


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

        async def force(_remote):
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
