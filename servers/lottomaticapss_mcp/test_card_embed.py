from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastmcp import Client

from .card_embed import (
    CARD_EMBED_HTML, CARD_EMBED_META_KEY, CARD_EMBED_URI, ECHARTS_CARD_HTML,
    ECHARTS_CARD_META_KEY, ECHARTS_CARD_URI, sign_card_embed_url,
)
from .metabase_client import MetabaseClient, MetabaseResult
from .visualization import saved_chart_payload

SECRET = "s" * 64
SITE = "https://analytics.example"


def _decode(segment: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


class SignCardEmbedUrlTests(unittest.TestCase):
    def test_native_contract_accepts_niuma_scalar_pivot_and_row(self):
        from .native_viewer import saved_visualization
        for display, settings in (
            ("scalar", {"scalar.field": "sum", "scalar.compact_primary_number": True}),
            ("pivot", {"pivot_table.column_split": {"rows": ["status"], "columns": [], "values": ["count"]}}),
            ("row", {"graph.dimensions": ["supplier"], "graph.metrics": ["count"]}),
        ):
            with self.subTest(display=display):
                result = saved_visualization({"id": 707, "display": display, "visualization_settings": settings})
                self.assertEqual(result["display"], display)
                self.assertEqual(result["settings"], settings)

    def test_saved_pie_implicit_columns_are_resolved_without_mutating_saved_settings(self):
        from .native_viewer import saved_visualization
        settings = {"pie.decimal_places": 2, "pie.percent_visibility": "legend", "pie.show_labels": False,
                    "pie.slice_threshold": 0, "column_settings": {'["name","sum"]': {"number_style": "currency"}}}
        metadata = [{"name": "Classificazione ODA", "source": "breakout", "base_type": "type/Text",
                 "effective_type": "type/Text", "field_ref": ["expression", "Classificazione ODA"]},
                {"name": "sum", "source": "aggregation", "base_type": "type/Decimal",
                 "effective_type": "type/Decimal", "field_ref": ["aggregation", 0]}]
        result = saved_visualization({"id": 842, "display": "pie", "visualization_settings": settings,
                                      "result_metadata": metadata})
        self.assertEqual(result["settings"]["pie.dimension"], ["Classificazione ODA"])
        self.assertEqual(result["settings"]["pie.metric"], "sum")
        self.assertEqual(result["settings"]["column_settings"], settings["column_settings"])
        self.assertNotIn("pie.dimension", settings)

    def test_saved_pie_ambiguous_columns_are_not_guessed(self):
        from .native_viewer import saved_visualization
        settings = {"pie.show_labels": False}
        metadata = [{"name": "first", "source": "breakout"}, {"name": "second", "source": "breakout"},
                    {"name": "sum", "source": "aggregation"}]
        result = saved_visualization({"id": 842, "display": "pie", "visualization_settings": settings,
                                      "result_metadata": metadata})
        self.assertEqual(result["settings"], settings)

    def test_saved_pie_explicit_columns_are_not_overridden(self):
        from .native_viewer import saved_visualization
        settings = {"pie.dimension": ["selected"], "pie.metric": "selected_metric"}
        result = saved_visualization({"id": 842, "display": "pie", "visualization_settings": settings,
                                      "result_metadata": [{"name": "other", "source": "breakout"},
                                                          {"name": "sum", "source": "aggregation"}]})
        self.assertEqual(result["settings"], settings)

    def test_native_saved_contract_retains_pie_and_combo_settings(self):
        from .native_viewer import saved_visualization
        for display in ("pie", "area", "combo"):
            settings = {"graph.dimensions": ["month"], "graph.metrics": ["count"]}
            result = saved_visualization({"id": 842, "display": display, "visualization_settings": settings})
            self.assertEqual(result["display"], display)
            self.assertEqual(result["settings"], settings)
            self.assertEqual(result["version"], 1)

    def test_native_assets_keep_api_origin_and_reject_path_traversal(self):
        import tempfile
        from pathlib import Path
        from . import native_viewer
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app" / "dist").mkdir(parents=True)
            (root / "app" / "dist" / "app.js").write_text("test")
            (root / "embed-mcp.html").write_text(
                '<script src="{{{instanceUrlRaw}}}/app/dist/app.js"></script><body>'
                '<script>window.metabaseConfig={instanceUrl:{{{instanceUrl}}}};</script></body>')
            with patch.object(native_viewer, "ASSET_ROOT", root):
                html = native_viewer.render_html("https://analytics.example", "https://gateway.example")
                self.assertIn("https://gateway.example/native-viewer/assets/app.js", html)
                self.assertIn('instanceUrl:"https://analytics.example"', html)
                self.assertIn('window.metabaseConfig.assetUrl="https://gateway.example/native-viewer/assets/"', html)
                self.assertEqual(native_viewer.asset_path("app.js"), root / "app" / "dist" / "app.js")
                with self.assertRaises(FileNotFoundError):
                    native_viewer.asset_path("../outside")

    def test_url_is_hs256_signed_for_the_card_with_expiry(self):
        url, expires_at = sign_card_embed_url(SITE + "/", SECRET, 936, ttl_seconds=600, now=1_000)
        self.assertTrue(url.startswith(f"{SITE}/embed/question/"))
        header, payload, signature = url.rsplit("/", 1)[1].split(".")
        expected = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        self.assertEqual(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)), expected)
        self.assertEqual(_decode(header), {"alg": "HS256", "typ": "JWT"})
        self.assertEqual(_decode(payload), {"resource": {"question": 936}, "params": {}, "exp": 1_600})
        self.assertEqual(expires_at, 1_600)
        self.assertNotIn(SECRET, url)

    def test_view_html_reads_meta_key_and_uses_app_refresh_tool(self):
        self.assertIn(CARD_EMBED_META_KEY, CARD_EMBED_HTML)
        self.assertIn("saved_card_embed_url", CARD_EMBED_HTML)
        self.assertIn("ui/initialize", CARD_EMBED_HTML)
        self.assertIn("openai:set_globals", CARD_EMBED_HTML)
        self.assertEqual(CARD_EMBED_HTML.count("<script>"), 1)

    def test_echarts_resource_is_pinned_and_reads_saved_metadata(self):
        self.assertIn("echarts@5.6.0", ECHARTS_CARD_HTML)
        self.assertIn("integrity=\"sha384-", ECHARTS_CARD_HTML)
        self.assertIn(ECHARTS_CARD_META_KEY, ECHARTS_CARD_HTML)
        self.assertIn("graph.dimensions", ECHARTS_CARD_HTML)
        self.assertIn("areaStyle", ECHARTS_CARD_HTML)
        self.assertIn("secondDimIndex", ECHARTS_CARD_HTML)
        self.assertIn("series_settings", ECHARTS_CARD_HTML)

    def test_saved_chart_payload_preserves_settings_and_bounds_rows(self):
        card = {"id": 840, "name": "Award trend", "display": "area",
                "visualization_settings": {"graph.dimensions": ["award_date"]}}
        result = {"data": {"cols": [{"name": "award_date"}, {"name": "sum", "base_type": "type/Float"}],
                           "rows": [[str(index), index] for index in range(4)]}}
        payload = saved_chart_payload(card, result, row_limit=2)
        self.assertEqual(payload["display"], "area")
        self.assertEqual(payload["settings"], card["visualization_settings"])
        self.assertEqual(payload["rows"], result["data"]["rows"][:2])
        self.assertEqual(payload["row_count"], 4)
        self.assertTrue(payload["truncated"])


class VisualizeCardToolTests(unittest.TestCase):
    def test_non_app_output_returns_data_without_native_or_embed_credentials(self):
        from . import server

        env = {"LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED": "false",
               "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "[]",
               "LOTTOMATICAPSS_GATEWAY_ENABLE_TOOLBOX": "false"}
        card = MetabaseResult({"id": 936, "name": "Saved combo", "display": "combo"}, "api")
        data = MetabaseResult({"data": {"cols": [{"name": "month"}, {"name": "count"}],
                                       "rows": [["2026-01", 2]]}}, "api")

        async def scenario(output):
            instance = server.create_mcp()
            with patch.object(server, "_ctx_or_current", return_value=SimpleNamespace(
                    client_supports_extension=lambda extension: False)):
                async with Client(instance) as client:
                    return await client.call_tool_mcp("visualize_card", {"card_id": 936, "output": output})

        for output in ("table", "auto"):
            with self.subTest(output=output), patch.dict(os.environ, env), \
                    patch.object(MetabaseClient, "api_get_card", AsyncMock(return_value=card)), \
                    patch.object(MetabaseClient, "api_run_card_query", AsyncMock(return_value=data)) as queried, \
                    patch.object(server, "construct_and_visualize_remote_query", AsyncMock()) as native, \
                    patch.object(server, "sign_card_embed_url") as guest:
                result = asyncio.run(scenario(output))
                queried.assert_awaited_once_with(936)
                native.assert_not_awaited()
                guest.assert_not_called()
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["rows"], [["2026-01", 2]])
                self.assertEqual(result.meta["lottomaticapss/rendering"]["renderer"], "table")
                self.assertNotIn(CARD_EMBED_META_KEY, result.meta)
                self.assertIn("no chart widget was prepared", result.content[0].text)

    def test_delegated_visualize_card_uses_native_query_without_guest_or_echarts(self):
        from mcp import types as mt
        from . import server

        env = {"LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED": "false",
               "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "[]",
               "LOTTOMATICAPSS_GATEWAY_ENABLE_TOOLBOX": "false"}
        query = {"database": 2, "type": "query", "query": {"source-table": "card__685"}}
        card = MetabaseResult({"id": 936, "display": "combo", "dataset_query": query}, "mcp")
        native = AsyncMock(return_value=mt.CallToolResult(content=[], structuredContent={"query": "test"}))
        guest = AsyncMock()
        echarts = AsyncMock()

        async def scenario():
            instance = server.create_mcp()
            with patch.object(server, "separation_enabled", return_value=True), \
                    patch.object(server, "_ctx_or_current", return_value=SimpleNamespace(
                        client_supports_extension=lambda extension: True)):
                async with Client(instance) as client:
                    return await client.call_tool_mcp("visualize_card", {"card_id": 936, "output": "auto"})

        with patch.dict(os.environ, env), \
                patch.object(MetabaseClient, "get_card", AsyncMock(return_value=card)), \
                patch.object(MetabaseClient, "api_get_card", guest), \
                patch.object(MetabaseClient, "api_run_card_query", echarts), \
                patch.object(server, "construct_and_visualize_remote_query", native):
            result = asyncio.run(scenario())
        native.assert_awaited_once()
        guest.assert_not_awaited()
        echarts.assert_not_awaited()
        self.assertFalse(result.is_error)
        self.assertEqual(result.meta["lottomaticapss/rendering"]["renderer"], "native-mcp")
        self.assertFalse(result.meta["lottomaticapss/rendering"]["saved_settings_preserved"])
        self.assertFalse(result.meta["lottomaticapss/rendering"]["browser_rendering_verified"])
        self.assertNotIn(CARD_EMBED_META_KEY, result.meta)
        self.assertIn("Saved display: combo", result.content[-1].text)
        self.assertIn("settings are not preserved", result.content[-1].text)
        self.assertIn("No ECharts fallback", result.content[-1].text)

    def run_tool(self, *, enable_embedding: bool, secret: str | None, tool: str = "visualize_card"):
        env = {
            "LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED": "false",
            "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "[]",
            "LOTTOMATICAPSS_GATEWAY_ENABLE_TOOLBOX": "false",
            "METABASE_SITE_URL": SITE,
            "METABASE_EMBEDDING_SECRET_KEY": secret or "",
        }

        async def api_get_card(self, card_id):
            return MetabaseResult({"id": card_id, "name": "Numero ODA per Quarter e Mese", "display": "combo",
                                   "enable_embedding": enable_embedding}, "api")

        async def scenario():
            from .server import create_mcp
            async with Client(create_mcp()) as client:
                return await client.call_tool_mcp(tool, {"card_id": 936})

        with patch.dict(os.environ, env), patch.object(MetabaseClient, "api_get_card", api_get_card):
            return asyncio.run(scenario())

    def test_published_card_returns_signed_embed_in_meta_only(self):
        result = self.run_tool(enable_embedding=True, secret=SECRET)
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content,
                         {"card_id": 936, "name": "Numero ODA per Quarter e Mese", "display": "combo", "published": True})
        url = result.meta[CARD_EMBED_META_KEY]["url"]
        self.assertTrue(url.startswith(f"{SITE}/embed/question/"))
        visible = json.dumps([b.model_dump() for b in result.content]) + json.dumps(result.structured_content)
        self.assertNotIn("/embed/question/", visible)
        self.assertNotIn(SECRET, visible + json.dumps(result.meta))

    def test_unpublished_card_points_to_query_fallback(self):
        result = self.run_tool(enable_embedding=False, secret=SECRET)
        self.assertFalse(result.structured_content["published"])
        self.assertNotIn(CARD_EMBED_META_KEY, result.meta or {})
        self.assertIn("visualize_card_query", result.content[0].text)
        self.assertIn("not published", result.content[0].text)

    def test_missing_secret_is_reported_without_signing(self):
        result = self.run_tool(enable_embedding=True, secret=None)
        self.assertFalse(result.structured_content["published"])
        self.assertIn("not configured", result.content[0].text)

    def test_app_refresh_tool_issues_fresh_url(self):
        result = self.run_tool(enable_embedding=True, secret=SECRET, tool="saved_card_embed_url")
        self.assertTrue(result.meta[CARD_EMBED_META_KEY]["url"].startswith(f"{SITE}/embed/question/"))

    def test_view_resource_allows_framing_only_analytics_origin(self):
        env = {"LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED": "false", "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "[]",
               "LOTTOMATICAPSS_GATEWAY_ENABLE_TOOLBOX": "false", "METABASE_SITE_URL": SITE}

        async def scenario():
            from .server import create_mcp
            async with Client(create_mcp()) as client:
                tools = {t.name: t for t in (await client.list_tools_mcp()).tools}
                return tools, await client.read_resource_mcp(CARD_EMBED_URI)

        with patch.dict(os.environ, env):
            tools, resource = asyncio.run(scenario())
        self.assertEqual(tools["visualize_card"].meta["ui"]["resourceUri"], CARD_EMBED_URI)
        self.assertEqual(tools["visualize_card"].meta["openai/outputTemplate"], CARD_EMBED_URI)
        self.assertEqual(tools["saved_card_embed_url"].meta["ui"]["visibility"], ["app"])
        self.assertTrue(tools["saved_card_embed_url"].meta["openai/widgetAccessible"])
        (content,) = resource.contents
        self.assertEqual(content.mime_type, "text/html;profile=mcp-app")
        self.assertEqual(content.meta["ui"]["csp"]["frameDomains"], [SITE])
        self.assertEqual(content.meta["ui"]["domain"], SITE)
        self.assertEqual(content.meta["openai/widgetCSP"]["frame_domains"], [SITE])

    def test_echarts_tool_uses_scoped_saved_query_data(self):
        env = {
            "LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED": "false",
            "LOTTOMATICAPSS_GATEWAY_REMOTES_JSON": "[]",
            "LOTTOMATICAPSS_GATEWAY_ENABLE_TOOLBOX": "false",
            "METABASE_SITE_URL": SITE,
        }
        async def api_get_card(self, card_id):
            return MetabaseResult({"id": card_id, "name": "Award trend", "display": "area",
                "visualization_settings": {"graph.dimensions": ["award_date"], "graph.metrics": ["sum"]}}, "api")
        async def api_run_card_query(self, card_id, *, parameters=None):
            return MetabaseResult({"data": {"cols": [{"name": "award_date"},
                {"name": "sum", "base_type": "type/Float"}], "rows": [["2026-01-01", 2.5]]}}, "api")
        async def scenario():
            from .server import create_mcp
            async with Client(create_mcp()) as client:
                tools = {tool.name: tool for tool in (await client.list_tools_mcp()).tools}
                result = await client.call_tool_mcp("visualize_card_echarts", {"card_id": 840})
                return tools, result
        with patch.dict(os.environ, env), \
                patch.object(MetabaseClient, "api_get_card", api_get_card), \
                patch.object(MetabaseClient, "api_run_card_query", api_run_card_query):
            tools, result = asyncio.run(scenario())
        self.assertEqual(tools["visualize_card_echarts"].meta["ui"]["resourceUri"], ECHARTS_CARD_URI)
        self.assertIn("One call creates", tools["visualize_card_echarts"].description)
        self.assertIn("do not call another visualization tool", tools["visualize_card_echarts"].description)
        self.assertEqual(result.structured_content["display"], "area")
        chart = result.meta[ECHARTS_CARD_META_KEY]
        self.assertEqual(chart["rows"], [["2026-01-01", 2.5]])
        self.assertEqual(chart["settings"]["graph.dimensions"], ["award_date"])
        self.assertIn("connected Ditra Analytics account", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
