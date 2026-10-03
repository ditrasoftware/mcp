from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from .white_label import BRAND_FUNCTION_JS, white_label_analytics_renderer

RENDERER = (
    "<!-- metabase-mcp-asset: visualize-query ui://metabase/visualize-query.html -->\n"
    '<!doctype html><html lang="en"><head><meta charset="UTF-8"/><title>Metabase</title>'
    "<script>window.Metabase = window.Metabase || {};</script>"
    '<script defer="defer" src="https://analytics.ditra.io/app/dist/app-embed-mcp.js" '
    'onerror="Metabase.AssetErrorLoad(this)"></script></head><body><div id="root"></div></body></html>'
)

CASES = {
    "Explore in Metabase": "Explore in Ditra Analytics",
    "Could not connect to Metabase. Make sure this MCP client is enabled in AI settings and that Metabase is reachable.":
        "Could not connect to Ditra Analytics. Make sure this MCP client is enabled in AI settings and that Ditra Analytics is reachable.",
    "Impossibile connettersi a Metabase. Assicurati che Metabase sia raggiungibile.":
        "Impossibile connettersi a Ditra Analytics. Assicurati che Ditra Analytics sia raggiungibile.",
    "Metabase's docs, metabase guide": "Ditra Analytics's docs, Ditra Analytics guide",
    "https://www.metabase.com/docs": "https://www.metabase.com/docs",
    "see metabase.com": "see metabase.com",
    "window.Metabase.AssetErrorLoad": "window.Metabase.AssetErrorLoad",
    "metabase-mcp-asset ui://metabase/x": "metabase-mcp-asset ui://metabase/x",
    "MetabaseClient": "MetabaseClient",
}


class WhiteLabelRendererTests(unittest.TestCase):
    def test_brand_function_rewrites_visible_text_only(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        script = f"{BRAND_FUNCTION_JS}\nconsole.log(JSON.stringify({json.dumps(list(CASES))}.map(brand)));"
        output = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(dict(zip(CASES, json.loads(output))), CASES)

    def test_renderer_html_is_branded_once_before_metabase_scripts(self):
        branded = white_label_analytics_renderer(RENDERER)
        self.assertIn("<title>Ditra Analytics</title>", branded)
        self.assertNotIn("<title>Metabase</title>", branded)
        self.assertLess(branded.index("MutationObserver"), branded.index("app-embed-mcp.js"))
        self.assertEqual(white_label_analytics_renderer(branded), branded)
        self.assertIn('src="https://analytics.ditra.io/app/dist/app-embed-mcp.js"', branded)


if __name__ == "__main__":
    unittest.main()
