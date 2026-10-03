from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from fastmcp import Client

from .card_embed import CARD_EMBED_HTML, CARD_EMBED_META_KEY, CARD_EMBED_URI, sign_card_embed_url
from .metabase_client import MetabaseClient, MetabaseResult

SECRET = "s" * 64
SITE = "https://analytics.example"


def _decode(segment: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


class SignCardEmbedUrlTests(unittest.TestCase):
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


class VisualizeCardToolTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
