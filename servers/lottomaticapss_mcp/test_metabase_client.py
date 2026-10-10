from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from .metabase_client import MetabaseClient, MetabaseClientError
from .artifacts.tools.local import _page_metadata
from .settings import MetabaseSettings


def run(coro):
    return asyncio.run(coro)


def settings(**overrides):
    values = {
        "site_url": "https://analytics.example.test",
        "mcp_url": "https://analytics.example.test/api/metabase-mcp",
        "api_key": "test-key",
        "default_page_size": 50,
        "max_page_size": 200,
    }
    values.update(overrides)
    return MetabaseSettings(**values)


class MetabaseClientTests(unittest.TestCase):
    def run_http(self, operation, handler):
        async_client = httpx.AsyncClient
        transport = httpx.MockTransport(handler)
        with patch.object(httpx, "AsyncClient",
                   lambda **kwargs: async_client(transport=transport, **kwargs)):
            return run(operation)

    @staticmethod
    def mcp_response(request_id, *, result=None, error=None, headers=None):
        payload = {"jsonrpc": "2.0", "id": request_id}
        payload["error" if error is not None else "result"] = error if error is not None else result
        return httpx.Response(200, headers=headers,
                              text="data: " + json.dumps(payload) + "\n\n")

    def test_http_mcp_denials_at_each_phase_never_call_rest(self):
        for status_code in (401, 403):
            for phase in ("initialize", "notifications/initialized", "tools/call"):
                with self.subTest(status_code=status_code, phase=phase):
                    client = MetabaseClient(settings())

                    def handler(request):
                        self.assertEqual(request.url.path, "/api/metabase-mcp")
                        if request.method == "DELETE":
                            return httpx.Response(200)
                        payload = json.loads(request.content)
                        if payload["method"] == phase:
                            return httpx.Response(status_code)
                        if payload["method"] == "initialize":
                            return self.mcp_response(1, result={}, headers={"mcp-session-id": "session-1"})
                        return httpx.Response(202)

                    with self.assertRaises(MetabaseClientError) as caught:
                        self.run_http(client.search("orders"), handler)
                    self.assertEqual(caught.exception.status_code, status_code)

    def test_application_errors_without_status_do_not_fallback(self):
        failures = [
            {"isError": True, "content": [{"type": "text", "text": "Insufficient scope to call tool: search"}]},
            {"isError": True, "content": [{"type": "text", "text": "You do not have permissions to do that."}]},
            {"isError": True, "content": [{"type": "text", "text": "Localized or unknown error"}]},
            {"isError": True, "content": []},
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                client = MetabaseClient(settings())

                def handler(request):
                    self.assertEqual(request.url.path, "/api/metabase-mcp")
                    if request.method == "DELETE":
                        return httpx.Response(200)
                    payload = json.loads(request.content)
                    if payload["method"] == "initialize":
                        return self.mcp_response(1, result={}, headers={"mcp-session-id": "session-1"})
                    if payload["method"] == "notifications/initialized":
                        return httpx.Response(202)
                    return self.mcp_response(2, result=failure)

                with self.assertRaises(MetabaseClientError) as caught:
                    self.run_http(client.search("orders"), handler)
                self.assertFalse(caught.exception.allow_api_fallback)

    def test_jsonrpc_unknown_errors_do_not_fallback(self):
        for error in ({"code": -32603, "message": "Permission denied"},
                      {"code": -32000, "message": "Unknown application failure"}):
            with self.subTest(error=error):
                client = MetabaseClient(settings())

                def handler(request):
                    self.assertEqual(request.url.path, "/api/metabase-mcp")
                    return self.mcp_response(1, error=error)

                with self.assertRaises(MetabaseClientError) as caught:
                    self.run_http(client.search("orders"), handler)
                self.assertFalse(caught.exception.allow_api_fallback)

    def test_unknown_tool_and_method_preserve_rest_fallback(self):
        for missing in ("tool", "method"):
            with self.subTest(missing=missing):
                client = MetabaseClient(settings())
                rest_calls = []

                def handler(request):
                    if request.url.path == "/api/search":
                        rest_calls.append(request)
                        return httpx.Response(200, json=[{"id": 2}])
                    self.assertEqual(request.url.path, "/api/metabase-mcp")
                    if request.method == "DELETE":
                        return httpx.Response(200)
                    payload = json.loads(request.content)
                    if payload["method"] == "initialize":
                        if missing == "method":
                            return self.mcp_response(1, error={"code": -32601, "message": "Method not found"})
                        return self.mcp_response(1, result={}, headers={"mcp-session-id": "session-1"})
                    if payload["method"] == "notifications/initialized":
                        return httpx.Response(202)
                    return self.mcp_response(2, result={"isError": True, "content": [
                        {"type": "text", "text": "Unknown tool: search"}]})

                result = self.run_http(client.search("orders"), handler)
                self.assertEqual(result.backend, "api")
                self.assertEqual(result.data, [{"id": 2}])
                self.assertEqual(len(rest_calls), 1)

    def test_password_session_renews_once_without_rest_fallback(self):
        for renewed_status in (200, 401, 403):
            with self.subTest(renewed_status=renewed_status):
                client = MetabaseClient(settings(api_key=None, username="analyst", password="test-password"))
                client._session_token = "expired"
                login_calls = []
                initialize_tokens = []

                def handler(request):
                    if request.url.path == "/api/session":
                        login_calls.append(request)
                        self.assertEqual(json.loads(request.content),
                                         {"username": "analyst", "password": "test-password"})
                        return httpx.Response(200, json={"id": "renewed"})
                    self.assertEqual(request.url.path, "/api/metabase-mcp")
                    if request.method == "DELETE":
                        return httpx.Response(200)
                    payload = json.loads(request.content)
                    if payload["method"] == "initialize":
                        token = request.headers["X-Metabase-Session"]
                        initialize_tokens.append(token)
                        if token == "expired":
                            return httpx.Response(401)
                        if renewed_status != 200:
                            return httpx.Response(renewed_status)
                        return self.mcp_response(1, result={}, headers={"mcp-session-id": "session-1"})
                    if payload["method"] == "notifications/initialized":
                        return httpx.Response(202)
                    return self.mcp_response(2, result={"structuredContent": {"data": [{"id": 1}]}})

                if renewed_status == 200:
                    result = self.run_http(client.search("orders"), handler)
                    self.assertEqual(result.backend, "mcp")
                    self.assertEqual(result.data, {"data": [{"id": 1}]})
                else:
                    with self.assertRaises(MetabaseClientError) as caught:
                        self.run_http(client.search("orders"), handler)
                    self.assertEqual(caught.exception.status_code, renewed_status)
                self.assertEqual(len(login_calls), 1)
                self.assertEqual(initialize_tokens, ["expired", "renewed"])

    def test_connection_failure_preserves_rest_fallback(self):
        client = MetabaseClient(settings())

        def handler(request):
            if request.url.path == "/api/metabase-mcp":
                raise httpx.ConnectError("MCP unavailable", request=request)
            self.assertEqual(request.url.path, "/api/search")
            return httpx.Response(200, json=[{"id": 2}])

        result = self.run_http(client.search("orders"), handler)
        self.assertEqual(result.backend, "api")
        self.assertEqual(result.data, [{"id": 2}])

    def test_api_only_mode_keeps_explicit_rest_access(self):
        client = MetabaseClient(settings(access_mode="api_only"))

        async def mcp_call(*args, **kwargs):
            raise AssertionError("API-only mode must not probe MCP")

        async def request(*args, **kwargs):
            return [{"id": 2}]

        with patch.object(client, "_mcp_call", mcp_call), patch.object(client, "_request", request):
            result = run(client.search("orders"))
        self.assertEqual(result.backend, "api")
        self.assertEqual(result.data, [{"id": 2}])

    def test_filtered_search_selects_rest_without_mcp_probe(self):
        client = MetabaseClient(settings())

        async def mcp_call(*args, **kwargs):
            raise AssertionError("Model-filtered search uses REST directly")

        async def request(*args, **kwargs):
            self.assertEqual(kwargs["params"]["models"], ["card"])
            return [{"id": 2}]

        with patch.object(client, "_mcp_call", mcp_call), patch.object(client, "_request", request):
            result = run(client.search("orders", models=["card"]))
        self.assertEqual(result.backend, "api")

    def test_rest_password_session_renewal_is_unchanged(self):
        client = MetabaseClient(settings(api_key=None, username="analyst", password="test-password"))
        client._session_token = "expired"
        search_tokens = []

        def handler(request):
            if request.url.path == "/api/session":
                return httpx.Response(200, json={"id": "renewed"})
            self.assertEqual(request.url.path, "/api/search")
            token = request.headers["X-Metabase-Session"]
            search_tokens.append(token)
            return httpx.Response(401) if token == "expired" else httpx.Response(200, json=[{"id": 2}])

        result = self.run_http(client.api_search("orders"), handler)
        self.assertEqual(result.backend, "api")
        self.assertEqual(result.data, [{"id": 2}])
        self.assertEqual(search_tokens, ["expired", "renewed"])

    def test_page_metadata_supports_response_envelope(self):
        page = _page_metadata(
            {"data": [{"id": 1}, {"id": 2}], "total": 5}, 2, 0
        )
        self.assertEqual(page["returned"], 2)
        self.assertEqual(page["total"], 5)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_offset"], 2)

    def test_search_prefers_mcp(self):
        client = MetabaseClient(settings())

        async def mcp_call(tool_name, arguments):
            self.assertEqual(tool_name, "search")
            self.assertEqual(
                arguments, {"term_queries": "revenue", "semantic_queries": None}
            )
            return {"data": [{"id": 1}]}

        async def request(*args, **kwargs):
            raise AssertionError("REST should not be called")

        with patch.object(client, "_mcp_call", mcp_call), patch.object(
            client, "_request", request
        ):
            result = run(client.search("revenue"))
        self.assertEqual(result.backend, "mcp")
        self.assertEqual(result.data, {"data": [{"id": 1}]})

    def test_search_falls_back_to_api(self):
        client = MetabaseClient(settings())

        async def mcp_call(*args, **kwargs):
            raise MetabaseClientError("unavailable")

        async def request(method, path, *, params=None, **kwargs):
            self.assertEqual((method, path), ("GET", "/api/search"))
            self.assertEqual(params, {"q": "revenue", "limit": 50, "offset": 0})
            return [{"id": 2}]

        with patch.object(client, "_mcp_call", mcp_call), patch.object(
            client, "_request", request
        ):
            result = run(client.search("revenue"))
        self.assertEqual(result.backend, "api")
        self.assertEqual(result.fallback_reason, "MetabaseClientError")
        self.assertEqual(result.data, [{"id": 2}])

    def test_mcp_auth_failures_do_not_call_api(self):
        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                client = MetabaseClient(settings())
                failure = MetabaseClientError("access denied", status_code=status_code)

                async def mcp_call(*args, **kwargs):
                    raise failure

                async def request(*args, **kwargs):
                    raise AssertionError("REST must not bypass MCP authorization")

                with patch.object(client, "_mcp_call", mcp_call), patch.object(client, "_request", request):
                    with self.assertRaises(MetabaseClientError) as caught:
                        run(client.search("orders"))
                self.assertIs(caught.exception, failure)

    def test_non_auth_http_failures_preserve_api_fallback(self):
        for status_code in (404, 405, 429, 500, 501, 503):
            with self.subTest(status_code=status_code):
                client = MetabaseClient(settings())

                async def mcp_call(*args, **kwargs):
                    raise MetabaseClientError("MCP unavailable", status_code=status_code)

                async def request(*args, **kwargs):
                    return [{"id": 2}]

                with patch.object(client, "_mcp_call", mcp_call), patch.object(client, "_request", request):
                    result = run(client.search("orders"))
                self.assertEqual(result.backend, "api")
                self.assertEqual(result.data, [{"id": 2}])

    def test_disabled_fallback_does_not_call_api(self):
        client = MetabaseClient(settings(api_fallback_enabled=False))

        async def mcp_call(*args, **kwargs):
            raise MetabaseClientError("unavailable", status_code=503)

        async def request(*args, **kwargs):
            raise AssertionError("REST fallback is disabled")

        with patch.object(client, "_mcp_call", mcp_call), patch.object(client, "_request", request):
            with self.assertRaises(MetabaseClientError):
                run(client.search("orders"))

    def test_explicit_api_search_propagates_paging(self):
        client = MetabaseClient(settings())

        async def request(method, path, *, params=None, **kwargs):
            self.assertEqual(
                params,
                {"q": "orders", "limit": 25, "offset": 75, "models": ["card"]},
            )
            return [1, 2]

        with patch.object(client, "_request", request):
            result = run(
                client.api_search("orders", models=["card"], limit=25, offset=75)
            )
        self.assertEqual(result.backend, "api")
        self.assertEqual(result.data, [1, 2])

    def test_collection_paging_is_bounded(self):
        client = MetabaseClient(settings())

        with self.assertRaisesRegex(MetabaseClientError, "between 1 and 200"):
            run(client.list_collection_items(6, limit=201))
        with self.assertRaisesRegex(MetabaseClientError, "zero or greater"):
            run(client.list_collection_items(6, offset=-1))

    def test_dashboard_card_listing_defaults_to_complete_compact_result(self):
        client = MetabaseClient(settings())
        dashboard = {
            "id": 30,
            "name": "Dashboard",
            "dashcards": [
                {
                    "id": index + 1000,
                    "dashboard_tab_id": 38,
                    "card": {
                        "id": index + 800,
                        "name": f"Card {index}",
                        "display": "table",
                    },
                }
                for index in range(138)
            ],
        }

        async def request(*args, **kwargs):
            return dashboard

        with patch.object(client, "_request", request):
            result = run(client.list_dashboard_cards(30))
        self.assertEqual(result.backend, "api")
        self.assertEqual(result.data["total"], 138)
        self.assertEqual(result.data["question_card_count"], 138)
        self.assertEqual(result.data["virtual_card_count"], 0)
        self.assertEqual(len(result.data["data"]), 138)
        self.assertEqual(result.data["data"][-1]["card_id"], 937)
        self.assertNotIn("description", result.data["data"][0])

    def test_parameterized_question_uses_api(self):
        client = MetabaseClient(settings())

        async def request(method, path, *, json=None, **kwargs):
            self.assertEqual(path, "/api/card/841/query")
            self.assertEqual(json, {"parameters": [{"type": "date"}]})
            return {"row_count": 1}

        async def mcp_call(*args, **kwargs):
            raise AssertionError("MCP cannot preserve REST parameter bindings")

        with patch.object(client, "_request", request), patch.object(
            client, "_mcp_call", mcp_call
        ):
            result = run(
                client.run_card_query(841, parameters=[{"type": "date"}])
            )
        self.assertEqual(result.backend, "api")
        self.assertEqual(
            result.fallback_reason, "parameterized_question_requires_api"
        )


if __name__ == "__main__":
    unittest.main()
