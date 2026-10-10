from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ASSET_ROOT = Path(__file__).parent / "native_viewer_assets"
NATIVE_VIEWER_URI = "ui://ditra_analytics/metabase/visualize-query.html"
SUPPORTED_DISPLAYS = {"bar", "row", "line", "area", "pie", "combo", "table", "scalar", "pivot"}


def enabled() -> bool:
    return os.getenv("LOTTOMATICAPSS_NATIVE_SAVED_VIEWER_ENABLED", "false").lower() == "true"


def saved_visualization(card: dict) -> dict:
    display = card.get("display")
    settings = card.get("visualization_settings", {})
    if settings is None:
        settings = {}
    if display not in SUPPORTED_DISPLAYS or not isinstance(settings, dict):
        raise ValueError("Saved visualization type or settings are unsupported by the native viewer")
    settings = dict(settings)
    if display == "pie" and ("pie.dimension" not in settings or "pie.metric" not in settings):
        columns = card.get("result_metadata") or []
        if isinstance(columns, list) and all(isinstance(column, dict) for column in columns):
            metrics = [column for column in columns if column.get("source") == "aggregation"]
            dimensions = [column for column in columns if column.get("source") == "breakout"]
            if len(metrics) == 1 and len(dimensions) == 1:
                if isinstance(dimensions[0].get("name"), str) and isinstance(metrics[0].get("name"), str):
                    settings.setdefault("pie.dimension", [dimensions[0]["name"]])
                    settings.setdefault("pie.metric", metrics[0]["name"])
    return {"version": 1, "display": display, "settings": settings,
            "name": str(card.get("name") or f"Card {card.get('id')}")[:160]}


def asset_path(name: str) -> Path:
    root = ASSET_ROOT.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise FileNotFoundError("Native viewer asset not found")
    if not path.is_file():
        path = (root / "app" / "dist" / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("Native viewer asset not found")
    return path


def render_html(site_url: str, gateway_url: str) -> str:
    for url in (site_url, gateway_url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Native viewer requires configured HTTPS origins")
    asset_url = gateway_url.rstrip("/") + "/native-viewer/assets/"
    html = asset_path("embed-mcp.html").read_text(encoding="utf-8")
    html = html.replace("{{{instanceUrlRaw}}}/app/dist/", asset_url)
    html = html.replace("{{{instanceUrlRaw}}}", site_url.rstrip("/"))
    html = html.replace("{{{instanceUrl}}}", json.dumps(site_url.rstrip("/")))
    config = "<script>window.metabaseConfig.assetUrl=" + json.dumps(asset_url) + ";</script>"
    return html.replace("</body>", config + "</body>")