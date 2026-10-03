from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

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
