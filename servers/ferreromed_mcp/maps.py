from __future__ import annotations

import json
import math
import secrets
from textwrap import dedent
import time
from typing import Any, Literal
import base64
import asyncio

import httpx
from fastmcp import FastMCP
from fastmcp.server.context import Context
from starlette.responses import Response

from prefab_ui.app import PrefabApp
from prefab_ui.components import Badge, Card, Column, Embed, Heading, Muted, Row
from prefab_ui.components.data_table import DataTable, DataTableColumn


LocationKind = Literal["warehouse", "pharmacy"]
MapMode = Literal["all", "nearest"]
RenderMode = Literal["mosaic", "leaflet_preloaded"]

_TILE_MIN_Z = 0
_TILE_MAX_Z = 19


_EMBED_TTL_SECONDS = 10 * 60
_EMBED_MAX_ENTRIES = 200
_EMBED_HTML_CACHE: dict[str, tuple[float, str]] = {}

_TILE_TTL_SECONDS = 30 * 60
_TILE_MAX_ENTRIES = 1500
_TILE_B64_CACHE: dict[str, tuple[float, str]] = {}

# Tile fetch protection (best-effort, per-process)
_TILE_MAX_CONCURRENT_FETCHES = 6
_TILE_FETCH_SEM = asyncio.Semaphore(_TILE_MAX_CONCURRENT_FETCHES)

_TILE_RATE_CAPACITY = 120.0  # burst
_TILE_RATE_REFILL_PER_SEC = 2.0  # 120/min
_TILE_RATE_STATE: dict[str, tuple[float, float]] = {}  # ip -> (tokens, last_ts)
_TILE_RATE_STALE_SECONDS = 20 * 60
_TILE_RATE_MAX_CLIENTS = 5000

# 1x1 transparent PNG (used as a graceful fallback tile).
_TRANSPARENT_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6X7n1kAAAAASUVORK5CYII="
)


def _cache_put_html(html: str) -> str:
    # Opportunistic cleanup.
    now = time.time()
    expired = [k for k, (ts, _) in _EMBED_HTML_CACHE.items() if now - ts > _EMBED_TTL_SECONDS]
    for k in expired:
        _EMBED_HTML_CACHE.pop(k, None)

    # Keep cache bounded.
    if len(_EMBED_HTML_CACHE) >= _EMBED_MAX_ENTRIES:
        # Drop oldest ~10%.
        to_drop = sorted(_EMBED_HTML_CACHE.items(), key=lambda kv: kv[1][0])[: max(1, _EMBED_MAX_ENTRIES // 10)]
        for k, _ in to_drop:
            _EMBED_HTML_CACHE.pop(k, None)

    token = secrets.token_urlsafe(16)
    _EMBED_HTML_CACHE[token] = (now, html)
    return token


def _cache_get_html(token: str) -> str | None:
    now = time.time()
    item = _EMBED_HTML_CACHE.get(token)
    if not item:
        return None
    ts, html = item
    if now - ts > _EMBED_TTL_SECONDS:
        _EMBED_HTML_CACHE.pop(token, None)
        return None
    return html


def _tile_cache_get(key: str) -> str | None:
    now = time.time()
    item = _TILE_B64_CACHE.get(key)
    if not item:
        return None
    ts, b64 = item
    if now - ts > _TILE_TTL_SECONDS:
        _TILE_B64_CACHE.pop(key, None)
        return None
    return b64


def _tile_cache_put(key: str, b64: str) -> None:
    now = time.time()
    # Opportunistic cleanup.
    expired = [k for k, (ts, _) in _TILE_B64_CACHE.items() if now - ts > _TILE_TTL_SECONDS]
    for k in expired:
        _TILE_B64_CACHE.pop(k, None)

    if len(_TILE_B64_CACHE) >= _TILE_MAX_ENTRIES:
        to_drop = sorted(_TILE_B64_CACHE.items(), key=lambda kv: kv[1][0])[: max(1, _TILE_MAX_ENTRIES // 10)]
        for k, _ in to_drop:
            _TILE_B64_CACHE.pop(k, None)

    _TILE_B64_CACHE[key] = (now, b64)


def _client_ip_from_request(request) -> str:
    headers = getattr(request, "headers", {})
    xff = headers.get("x-forwarded-for")
    if xff:
        # First IP in the chain is the original client in standard setups.
        ip = xff.split(",")[0].strip()
        if ip:
            return ip

    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None
    return str(host or "unknown")


def _tile_rate_allow(ip: str) -> bool:
    """Token bucket rate limiter (best-effort)."""
    now = time.time()

    # Opportunistic cleanup to avoid unbounded growth.
    if len(_TILE_RATE_STATE) > _TILE_RATE_MAX_CLIENTS:
        stale = [k for k, (_, ts) in _TILE_RATE_STATE.items() if now - ts > _TILE_RATE_STALE_SECONDS]
        for k in stale[: max(1, len(_TILE_RATE_STATE) // 10)]:
            _TILE_RATE_STATE.pop(k, None)

    tokens, last = _TILE_RATE_STATE.get(ip, (_TILE_RATE_CAPACITY, now))
    # Refill
    tokens = min(_TILE_RATE_CAPACITY, tokens + (now - last) * _TILE_RATE_REFILL_PER_SEC)
    allowed = tokens >= 1.0
    if allowed:
        tokens -= 1.0
    _TILE_RATE_STATE[ip] = (tokens, now)
    return allowed


# Intentionally small, built-in datasets for demo/showcase.
# For production, back these with a database or a geocoding + POI provider.
WAREHOUSES: list[dict[str, object]] = [
    {
        "id": "WH-PE",
        "name": "Pescara Warehouse",
        "city": "Pescara",
        "lat": 42.4618,
        "lng": 14.2161,
        "kind": "warehouse",
    },
    {
        "id": "WH-AQ",
        "name": "L'Aquila Warehouse",
        "city": "L'Aquila",
        "lat": 42.1369,
        "lng": 13.6103,
        "kind": "warehouse",
    },
    {
        "id": "WH-TE",
        "name": "Teramo Warehouse",
        "city": "Teramo",
        "lat": 42.6612,
        "lng": 13.6987,
        "kind": "warehouse",
    },
]

PHARMACIES: list[dict[str, object]] = [
    {
        "id": "PH-PE-001",
        "name": "Farmacia Centrale Pescara",
        "city": "Pescara",
        "lat": 42.4652,
        "lng": 14.2145,
        "kind": "pharmacy",
    },
    {
        "id": "PH-CH-001",
        "name": "Farmacia Centro Chieti",
        "city": "Chieti",
        "lat": 42.3487,
        "lng": 14.1675,
        "kind": "pharmacy",
    },
    {
        "id": "PH-SU-001",
        "name": "Farmacia Sulmona",
        "city": "Sulmona",
        "lat": 42.0494,
        "lng": 13.9257,
        "kind": "pharmacy",
    },
    {
        "id": "PH-VA-001",
        "name": "Farmacia Vasto",
        "city": "Vasto",
        "lat": 42.1115,
        "lng": 14.7065,
        "kind": "pharmacy",
    },
]

# Convenience place names for demos (no external geocoding).
KNOWN_PLACES: dict[str, tuple[float, float]] = {
    "L'Aquila": (42.1369, 13.6103),
    "Pescara": (42.4618, 14.2161),
    "Teramo": (42.6612, 13.6987),
    "Chieti": (42.3487, 14.1675),
    "Sulmona": (42.0494, 13.9257),
    "Vasto": (42.1115, 14.7065),
}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _lonlat_to_tile_xy(lng: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    xtile = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def _lonlat_to_pixel_xy(lng: float, lat: float, zoom: int) -> tuple[float, float]:
    n = 2**zoom
    x = (lng + 180.0) / 360.0 * n * 256.0
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * 256.0
    return x, y


async def _fetch_osm_tile_png(z: int, x: int, y: int) -> bytes | None:
    if z < _TILE_MIN_Z or z > _TILE_MAX_Z:
        return None
    n = 2**z
    # Wrap X around the dateline; clamp Y (no wrap).
    x = x % n
    if y < 0 or y >= n:
        return None

    key = f"{z}/{x}/{y}"
    cached = _tile_cache_get(key)
    if cached is not None:
        try:
            return base64.b64decode(cached)
        except Exception:
            pass

    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"User-Agent": "ferreromed-mcp-maps/1.0"})
    if r.status_code != 200:
        return None
    try:
        _tile_cache_put(key, base64.b64encode(r.content).decode("ascii"))
    except Exception:
        pass
    return r.content


async def _build_static_tile_mosaic_html(
    *,
    locations: list[dict[str, object]],
    zoom: int,
    title: str,
    grid: int = 3,
) -> str:
    """CSP-safe static map for sandboxed hosts (ChatGPT).

    Builds a small tile mosaic with data: URIs and overlays markers.
    This avoids external `img-src`/`frame-src` CSP blocks.
    """

    if not locations:
        return _build_leaflet_html(locations=[], zoom=zoom, title=title)

    grid = max(1, min(int(grid), 5))
    if grid % 2 == 0:
        grid += 1

    lats = [float(loc["lat"]) for loc in locations if loc.get("lat") is not None]
    lngs = [float(loc["lng"]) for loc in locations if loc.get("lng") is not None]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)

    cx, cy = _lonlat_to_tile_xy(center_lng, center_lat, zoom)
    half = grid // 2
    tiles: list[tuple[int, int, int]] = []
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            tiles.append((zoom, cx + dx, cy + dy))

    # Fetch tiles sequentially to be gentle to OSM; grid is small (<= 5x5).
    tile_data: dict[tuple[int, int, int], str] = {}
    for z, x, y in tiles:
        png = await _fetch_osm_tile_png(z, x, y)
        if png is None:
            continue
        b64 = base64.b64encode(png).decode("ascii")
        tile_data[(z, x, y)] = f"data:image/png;base64,{b64}"

    top_left_px_x = (cx - half) * 256.0
    top_left_px_y = (cy - half) * 256.0
    width = grid * 256
    height = grid * 256

    marker_divs: list[str] = []
    for loc in locations:
        lat = float(loc["lat"])
        lng = float(loc["lng"])
        px, py = _lonlat_to_pixel_xy(lng, lat, zoom)
        left = px - top_left_px_x
        top = py - top_left_px_y
        name = str(loc.get("name") or "")
        city = str(loc.get("city") or "")
        dist = loc.get("distance_km")
        subtitle = city
        if dist is not None:
            try:
                subtitle = f"{subtitle} ({float(dist):.1f} km)" if subtitle else f"{float(dist):.1f} km"
            except (TypeError, ValueError):
                pass
        label = (name + (" — " + subtitle if subtitle else "")).strip(" —")
        marker_divs.append(
            f"<div class='marker' style='left:{left:.1f}px;top:{top:.1f}px' title={json.dumps(label)}></div>"
        )

    tile_imgs: list[str] = []
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            x = cx + dx
            y = cy + dy
            src = tile_data.get((zoom, x, y))
            left = (dx + half) * 256
            top = (dy + half) * 256
            if src:
                tile_imgs.append(
                    f"<img class='tile' src='{src}' style='left:{left}px;top:{top}px' />"
                )
            else:
                tile_imgs.append(
                    f"<div class='tile missing' style='left:{left}px;top:{top}px'></div>"
                )

    return dedent(
        f"""\
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <style>
            html, body {{ margin: 0; padding: 0; }}
            .wrap {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; background: #f8fafc; }}
            .tile {{ position:absolute; width:256px; height:256px; image-rendering: auto; }}
            .tile.missing {{ background: repeating-linear-gradient(45deg, #eee, #eee 10px, #f7f7f7 10px, #f7f7f7 20px); }}
            .marker {{
              position:absolute;
              width: 14px;
              height: 14px;
              margin-left: -7px;
              margin-top: -7px;
              border-radius: 999px;
              background: #ef4444;
              border: 2px solid white;
              box-shadow: 0 1px 2px rgba(0,0,0,0.25);
            }}
            .legend {{
              position: absolute;
              top: 10px;
              left: 10px;
              z-index: 10;
              background: rgba(255,255,255,0.92);
              padding: 8px 10px;
              border-radius: 8px;
              font-family: system-ui;
              font-size: 12px;
            }}
          </style>
        </head>
        <body>
          <div class="wrap">
            <div class="legend"><strong>{title}</strong><br/>{len(locations)} markers • zoom {zoom}</div>
            {''.join(tile_imgs)}
            {''.join(marker_divs)}
          </div>
        </body>
        </html>
                """
    )


async def _build_static_tile_mosaic_interactive_html(
        *,
        locations: list[dict[str, object]],
        zoom: int,
        title: str,
        grid: int = 3,
        zoom_span: int = 1,
) -> str:
        """CSP-safe interactive zoom by preloading multiple zoom layers.

        This keeps everything self-contained (data: URIs), so ChatGPT CSP can't block it.
        Interaction is limited to changing zoom (no pan).
        """

        if not locations:
                return await _build_static_tile_mosaic_html(locations=[], zoom=zoom, title=title, grid=grid)

        grid = max(1, min(int(grid), 5))
        if grid % 2 == 0:
                grid += 1

        zoom = _clamp_zoom(int(zoom))
        zoom_span = max(0, min(int(zoom_span), 2))
        zoom_levels = [z for z in range(zoom - zoom_span, zoom + zoom_span + 1) if 1 <= z <= 18]
        if zoom not in zoom_levels:
                zoom_levels.append(zoom)
                zoom_levels = sorted(set(zoom_levels))

        lats = [float(loc["lat"]) for loc in locations if loc.get("lat") is not None]
        lngs = [float(loc["lng"]) for loc in locations if loc.get("lng") is not None]
        center_lat = sum(lats) / len(lats)
        center_lng = sum(lngs) / len(lngs)

        half = grid // 2
        width = grid * 256
        height = grid * 256

        # Fetch tiles for each zoom level.
        all_tile_data: dict[tuple[int, int, int], str] = {}
        centers: dict[int, tuple[int, int]] = {}

        for z in zoom_levels:
                cx, cy = _lonlat_to_tile_xy(center_lng, center_lat, z)
                centers[z] = (cx, cy)
                for dy in range(-half, half + 1):
                        for dx in range(-half, half + 1):
                                x = cx + dx
                                y = cy + dy
                                key = (z, x, y)
                                if key in all_tile_data:
                                        continue
                                png = await _fetch_osm_tile_png(z, x, y)
                                if png is None:
                                        continue
                                b64 = base64.b64encode(png).decode("ascii")
                                all_tile_data[key] = f"data:image/png;base64,{b64}"

        def layer_html(z: int) -> str:
                cx, cy = centers[z]
                top_left_px_x = (cx - half) * 256.0
                top_left_px_y = (cy - half) * 256.0

                tile_imgs: list[str] = []
                for dy in range(-half, half + 1):
                        for dx in range(-half, half + 1):
                                x = cx + dx
                                y = cy + dy
                                src = all_tile_data.get((z, x, y))
                                left = (dx + half) * 256
                                top = (dy + half) * 256
                                if src:
                                        tile_imgs.append(
                                                f"<img class='tile' src='{src}' style='left:{left}px;top:{top}px' />"
                                        )
                                else:
                                        tile_imgs.append(
                                                f"<div class='tile missing' style='left:{left}px;top:{top}px'></div>"
                                        )

                marker_divs: list[str] = []
                for loc in locations:
                        lat = float(loc["lat"])
                        lng = float(loc["lng"])
                        px, py = _lonlat_to_pixel_xy(lng, lat, z)
                        left = px - top_left_px_x
                        top = py - top_left_px_y
                        name = str(loc.get("name") or "")
                        city = str(loc.get("city") or "")
                        dist = loc.get("distance_km")
                        subtitle = city
                        if dist is not None:
                                try:
                                        subtitle = f"{subtitle} ({float(dist):.1f} km)" if subtitle else f"{float(dist):.1f} km"
                                except (TypeError, ValueError):
                                        pass
                        label = (name + (" — " + subtitle if subtitle else "")).strip(" —")
                        marker_divs.append(
                                f"<div class='marker' style='left:{left:.1f}px;top:{top:.1f}px' title={json.dumps(label)}></div>"
                        )

                return f"<div class='layer' data-zoom='{z}' style='display:none'>{''.join(tile_imgs)}{''.join(marker_divs)}</div>"

        layers = "".join(layer_html(z) for z in zoom_levels)
        zoom_list_json = json.dumps(zoom_levels)

        return dedent(
                f"""\
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8" />
                    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                    <style>
                        html, body {{ margin: 0; padding: 0; }}
                        .wrap {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; background: #f8fafc; }}
                        .tile {{ position:absolute; width:256px; height:256px; }}
                        .tile.missing {{ background: repeating-linear-gradient(45deg, #eee, #eee 10px, #f7f7f7 10px, #f7f7f7 20px); }}
                        .marker {{
                            position:absolute;
                            width: 14px;
                            height: 14px;
                            margin-left: -7px;
                            margin-top: -7px;
                            border-radius: 999px;
                            background: #ef4444;
                            border: 2px solid white;
                            box-shadow: 0 1px 2px rgba(0,0,0,0.25);
                            cursor: default;
                        }}
                        .legend {{
                            position: absolute;
                            top: 10px;
                            left: 10px;
                            z-index: 10;
                            background: rgba(255,255,255,0.92);
                            padding: 8px 10px;
                            border-radius: 8px;
                            font-family: system-ui;
                            font-size: 12px;
                            max-width: 260px;
                        }}
                        .controls {{ margin-top: 6px; display: flex; gap: 8px; align-items: center; }}
                        .btn {{
                            border: 1px solid rgba(0,0,0,0.15);
                            background: white;
                            border-radius: 8px;
                            padding: 4px 8px;
                            font-size: 12px;
                            cursor: pointer;
                        }}
                        .btn.primary {{ background: #111827; color: white; border-color: #111827; }}
                        .btn:disabled {{ opacity: 0.45; cursor: not-allowed; }}
                    </style>
                </head>
                <body>
                    <div class="wrap" id="wrap">
                        <div class="legend">
                            <strong>{title}</strong><br/>
                            <span id="meta">{len(locations)} markers</span>
                            <div class="controls">
                                <button class="btn" id="zoomOut">−</button>
                                <span style="font-family: system-ui; font-size: 12px;">Zoom <span id="zoomLabel"></span></span>
                                <button class="btn primary" id="zoomIn">+</button>
                            </div>
                            <div style="margin-top:6px; opacity:0.75">Tip: hover markers for labels</div>
                        </div>
                        {layers}
                    </div>

                    <script>
                        (function() {{
                            var zooms = {zoom_list_json};
                            var current = zooms.indexOf({zoom});
                            if (current < 0) current = 0;

                            var label = document.getElementById('zoomLabel');
                            var btnIn = document.getElementById('zoomIn');
                            var btnOut = document.getElementById('zoomOut');

                            function render() {{
                                var z = zooms[current];
                                label.textContent = String(z);
                                btnOut.disabled = current <= 0;
                                btnIn.disabled = current >= zooms.length - 1;
                                var layers = document.querySelectorAll('.layer');
                                for (var i = 0; i < layers.length; i++) {{
                                    layers[i].style.display = (layers[i].getAttribute('data-zoom') == String(z)) ? 'block' : 'none';
                                }}
                            }}

                            btnIn.addEventListener('click', function() {{ if (current < zooms.length - 1) {{ current++; render(); }} }});
                            btnOut.addEventListener('click', function() {{ if (current > 0) {{ current--; render(); }} }});
                            render();
                        }})();
                    </script>
                </body>
                </html>
                """
        )


def _clamp_zoom(zoom: int) -> int:
    return max(_TILE_MIN_Z, min(int(zoom), _TILE_MAX_Z))


def _normalize_place_key(s: str) -> str:
    return " ".join(s.strip().split())


def _parse_origin(origin: str | None) -> dict[str, object] | None:
    if not origin:
        return None

    s = origin.strip()
    if not s:
        return None

    # Accept: "lat,lng" (or "lat lng")
    for sep in (",", " "):
        if sep in s:
            parts = [p for p in s.replace(",", " ").split() if p]
            if len(parts) >= 2:
                try:
                    lat = float(parts[0])
                    lng = float(parts[1])
                except ValueError:
                    return None
                return {"name": "Custom", "lat": lat, "lng": lng}

    # Accept known place name (case-insensitive)
    key = _normalize_place_key(s)
    for place, (lat, lng) in KNOWN_PLACES.items():
        if place.lower() == key.lower():
            return {"name": place, "lat": lat, "lng": lng}

    return None


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _coerce_optional_int(value: int | str | None, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def _coerce_optional_float(value: float | str | None, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _coerce_optional_str(value: str | None, *, default: str | None = None) -> str | None:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def _coerce_custom_locations(locations: list[dict[str, Any]] | None) -> list[dict[str, object]]:
    if not locations:
        return []

    out: list[dict[str, object]] = []
    for idx, loc in enumerate(locations):
        if not isinstance(loc, dict):
            continue

        name = loc.get("name") or loc.get("label") or loc.get("title") or f"Location {idx + 1}"
        lat = _parse_float(loc.get("lat"))
        lng = _parse_float(loc.get("lng"))

        # Allow city-only locations that map to known places.
        if (lat is None or lng is None) and isinstance(loc.get("city"), str):
            city = _normalize_place_key(loc["city"])
            for place, (p_lat, p_lng) in KNOWN_PLACES.items():
                if place.lower() == city.lower():
                    lat = p_lat
                    lng = p_lng
                    break

        if lat is None or lng is None:
            # Skip entries we can't map.
            continue

        normalized: dict[str, object] = {
            "id": str(loc.get("id") or loc.get("code") or loc.get("key") or ""),
            "name": str(name),
            "city": str(loc.get("city") or ""),
            "kind": str(loc.get("kind") or "custom"),
            "lat": float(lat),
            "lng": float(lng),
        }

        # Carry through a few common optional fields.
        if loc.get("address"):
            normalized["address"] = str(loc.get("address"))
        if loc.get("source"):
            normalized["source"] = str(loc.get("source"))

        out.append(normalized)

    return out


def _select_locations(kind: LocationKind) -> list[dict[str, object]]:
    if kind == "warehouse":
        return [dict(x) for x in WAREHOUSES]
    return [dict(x) for x in PHARMACIES]


def _filter_locations(locations: list[dict[str, object]], query: str | None) -> list[dict[str, object]]:
    if not query:
        return locations
    q = query.strip().lower()
    if not q:
        return locations

    out: list[dict[str, object]] = []
    for loc in locations:
        hay = " ".join(
            str(loc.get(k) or "")
            for k in ("id", "name", "city", "kind")
        ).lower()
        if q in hay:
            out.append(loc)
    return out

def _public_base_url_from_ctx(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    rc = ctx.request_context
    if rc is None or rc.request is None:
        return None

    # Prefer forwarded headers when behind a proxy.
    headers = rc.request.headers
    host = headers.get("x-forwarded-host") or headers.get("host")
    scheme = headers.get("x-forwarded-proto") or getattr(rc.request.url, "scheme", None) or "https"
    if not host:
        return None
    return f"{scheme}://{host}"


def _build_leaflet_html(
    *,
    locations: list[dict[str, object]],
    zoom: int,
    title: str,
    tile_url_template: str = "/tiles/{z}/{x}/{y}.png",
) -> str:
    if not locations:
        # A minimal HTML shell; the UI will still show the empty table.
        return dedent(
            """\
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset=\"utf-8\" />
              <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
              <style>
                html, body { margin: 0; height: 100%; }
                #map { height: 420px; width: 100%; }
              </style>
            </head>
            <body>
              <div id=\"map\"></div>
                            <div style=\"padding: 12px; font-family: system-ui\">No locations to map.</div>
                        </body>
                        </html>
                        """
                )

    lats = [float(loc["lat"]) for loc in locations if loc.get("lat") is not None]
    lngs = [float(loc["lng"]) for loc in locations if loc.get("lng") is not None]
    avg_lat = sum(lats) / len(lats)
    avg_lng = sum(lngs) / len(lngs)

    payload = json.dumps(
        [
            {
                "id": str(loc.get("id", "")),
                "name": str(loc.get("name", "")),
                "city": str(loc.get("city", "")),
                "kind": str(loc.get("kind", "")),
                "lat": float(loc["lat"]),
                "lng": float(loc["lng"]),
                "distance_km": loc.get("distance_km"),
            }
            for loc in locations
        ]
    )

    # Tile URL can be relative (when this HTML is served from our server) or absolute
    # (when embedded via srcdoc inside a sandboxed host).
    return dedent(
        f"""\
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset=\"utf-8\" />
          <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />

          <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" />
          <script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>

          <style>
            html, body {{ margin: 0; height: 100%; }}
            #map {{ height: 420px; width: 100%; }}
            .legend {{
              position: absolute;
              top: 10px;
              left: 10px;
              z-index: 1000;
              background: rgba(255,255,255,0.92);
              padding: 8px 10px;
              border-radius: 8px;
              font-family: system-ui;
              font-size: 12px;
            }}
          </style>
        </head>

        <body>
          <div id=\"map\"></div>
          <div class=\"legend\"><strong>{title}</strong><br/>{len(locations)} markers</div>

          <script>
            var locations = {payload};
            var map = L.map('map').setView([{avg_lat}, {avg_lng}], {zoom});

                        L.tileLayer('{tile_url_template}', {{
              maxZoom: 19,
              attribution: '&copy; OpenStreetMap contributors'
            }}).addTo(map);

            var bounds = [];
            locations.forEach(function(loc) {{
              var label = loc.name;
              if (loc.city) label += ' — ' + loc.city;
              if (loc.distance_km !== null && loc.distance_km !== undefined) {{
                label += '<br/><small>' + Number(loc.distance_km).toFixed(1) + ' km</small>';
              }}
              L.marker([loc.lat, loc.lng]).addTo(map).bindPopup(label);
              bounds.push([loc.lat, loc.lng]);
            }});

            if (bounds.length > 1) {{
              map.fitBounds(bounds, {{ padding: [20, 20] }});
            }}

            setTimeout(function() {{ map.invalidateSize(); }}, 250);
          </script>
        </body>
        </html>
        """
    )


def _tile_xy_to_lonlat_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
        """Return bounds (west, south, east, north) for a WebMercator tile."""
        n = 2**z
        west = x / n * 360.0 - 180.0
        east = (x + 1) / n * 360.0 - 180.0

        def _y_to_lat(yy: int) -> float:
                # Inverse WebMercator
                lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * yy / n)))
                return math.degrees(lat_rad)

        north = _y_to_lat(y)
        south = _y_to_lat(y + 1)
        return (west, south, east, north)


async def _build_leaflet_preloaded_tiles_html(
        *,
        locations: list[dict[str, object]],
        zoom: int,
        title: str,
        grid: int = 3,
        zoom_span: int = 1,
    base_url: str | None = None,
) -> str:
        """Leaflet map with interactive pan/zoom using *preloaded* data-URI tiles.

        This preserves Leaflet interactivity while avoiding remote image loads
        (ChatGPT CSP often blocks img-src for external URLs).
        """

        if not locations:
                return await _build_static_tile_mosaic_interactive_html(locations=[], zoom=zoom, title=title, grid=grid)

        grid = max(1, min(int(grid), 5))
        if grid % 2 == 0:
                grid += 1

        zoom = _clamp_zoom(int(zoom))
        zoom_span = max(0, min(int(zoom_span), 3))
        zoom_levels = [z for z in range(zoom - zoom_span, zoom + zoom_span + 1) if 1 <= z <= 18]

        lats = [float(loc["lat"]) for loc in locations if loc.get("lat") is not None]
        lngs = [float(loc["lng"]) for loc in locations if loc.get("lng") is not None]
        center_lat = sum(lats) / len(lats)
        center_lng = sum(lngs) / len(lngs)

        half = grid // 2

        # Preload tiles into a key->dataURI dict. Keep it bounded.
        tiles: dict[str, str] = {}
        bounds_by_zoom: dict[int, tuple[float, float, float, float]] = {}

        for z in zoom_levels:
                cx, cy = _lonlat_to_tile_xy(center_lng, center_lat, z)
                min_x, max_x = cx - half, cx + half
                min_y, max_y = cy - half, cy + half

                # Compute lat/lng bounds for this zoom's tile extent.
                w1, s1, e1, n1 = _tile_xy_to_lonlat_bounds(z, min_x, max_y)
                w2, s2, e2, n2 = _tile_xy_to_lonlat_bounds(z, max_x, min_y)
                west = min(w1, w2)
                east = max(e1, e2)
                south = min(s1, s2)
                north = max(n1, n2)
                bounds_by_zoom[z] = (west, south, east, north)

                for y in range(min_y, max_y + 1):
                        for x in range(min_x, max_x + 1):
                                key = f"{z}/{x}/{y}"
                                if key in tiles:
                                        continue
                                png = await _fetch_osm_tile_png(z, x, y)
                                if png is None:
                                        continue
                                b64 = base64.b64encode(png).decode("ascii")
                                tiles[key] = f"data:image/png;base64,{b64}"

        # Build marker payload and avoid Leaflet default icon URLs by using circle markers.
        marker_payload = json.dumps(
                [
                        {
                                "name": str(loc.get("name") or ""),
                                "city": str(loc.get("city") or ""),
                                "kind": str(loc.get("kind") or ""),
                                "lat": float(loc["lat"]),
                                "lng": float(loc["lng"]),
                                "distance_km": loc.get("distance_km"),
                        }
                        for loc in locations
                ]
        )

        tiles_json = json.dumps(tiles)
        zoom_levels_json = json.dumps(zoom_levels)
        bounds_json = json.dumps({str(k): v for k, v in bounds_by_zoom.items()})
        base_url_json = json.dumps(base_url or "")

        # Fallback metadata: allows a self-contained interactive fallback (no Leaflet).
        fb_width = grid * 256
        fb_height = grid * 256

        fb_meta: dict[str, dict[str, int]] = {}
        fb_markers_by_zoom: dict[str, list[dict[str, object]]] = {}

        for z in zoom_levels:
            cx, cy = _lonlat_to_tile_xy(center_lng, center_lat, z)
            min_x, max_x = cx - half, cx + half
            min_y, max_y = cy - half, cy + half
            fb_meta[str(z)] = {
                "z": int(z),
                "min_x": int(min_x),
                "max_x": int(max_x),
                "min_y": int(min_y),
                "max_y": int(max_y),
                "width": int(fb_width),
                "height": int(fb_height),
            }

            top_left_px_x = min_x * 256.0
            top_left_px_y = min_y * 256.0
            pts: list[dict[str, object]] = []
            for loc in locations:
                try:
                    lat = float(loc["lat"])
                    lng = float(loc["lng"])
                except Exception:
                    continue

                px, py = _lonlat_to_pixel_xy(lng, lat, z)
                left = px - top_left_px_x
                top = py - top_left_px_y
                if left < -64 or top < -64 or left > fb_width + 64 or top > fb_height + 64:
                    continue

                label = str(loc.get("name") or "")
                city = str(loc.get("city") or "")
                if city:
                    label = f"{label} — {city}" if label else city
                pts.append({"left": round(left, 1), "top": round(top, 1), "title": label})

            fb_markers_by_zoom[str(z)] = pts

        fb_meta_json = json.dumps(fb_meta)
        fb_markers_json = json.dumps(fb_markers_by_zoom)

        # Pre-render fallback layers for each zoom for smoother switching (no DOM rebuild loops).
        fb_layers: list[str] = []
        for z in zoom_levels:
            meta = fb_meta[str(z)]
            layer_tiles: list[str] = []
            for yy in range(int(meta["min_y"]), int(meta["max_y"]) + 1):
                for xx in range(int(meta["min_x"]), int(meta["max_x"]) + 1):
                    key = f"{int(meta['z'])}/{xx}/{yy}"
                    src = tiles.get(key)
                    left = (xx - int(meta["min_x"])) * 256
                    top = (yy - int(meta["min_y"])) * 256
                    if src:
                        layer_tiles.append(
                            f"<img class='fb-tile' src='{src}' style='left:{left}px;top:{top}px' />"
                        )
                    else:
                        layer_tiles.append(
                            f"<div class='fb-tile fb-missing' style='left:{left}px;top:{top}px'></div>"
                        )

            layer_markers: list[str] = []
            for p in fb_markers_by_zoom.get(str(z), []):
                left = float(p.get("left") or 0.0)
                top = float(p.get("top") or 0.0)
                title_text = str(p.get("title") or "")
                layer_markers.append(
                    f"<div class='fb-marker' style='left:{left}px;top:{top}px' title={json.dumps(title_text)}></div>"
                )

            fb_layers.append(
                "<div class='fb-zlayer' data-z='"
                + str(int(z))
                + "' style='display:none'>"
                + "".join(layer_tiles)
                + "".join(layer_markers)
                + "</div>"
            )

        fb_layers_html = "".join(fb_layers)

        # Static fallback content (renders even with scripts disabled).
        fallback_html = (
            "<div id='fallback' class='fb-wrap' aria-label='Map preview'>"
            "<div class='fb-controls' aria-hidden='true'>"
            "<button id='fbZoomIn' type='button' class='fb-btn'>+</button>"
            "<button id='fbZoomOut' type='button' class='fb-btn'>−</button>"
            "<span id='fbZoomLabel' class='fb-zoom'></span>"
            "</div>"
            "<div id='fbViewport' class='fb-viewport'>"
            "<div id='fbContent' class='fb-content'>"
            + fb_layers_html
            + "</div>"
            "</div>"
            "</div>"
        )

        return dedent(
                f"""\
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset=\"utf-8\" />
                    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
                    <script>
                        (function() {{
                            // Some hosts (e.g., Claude) block certain CDNs. Try multiple.
                            var cssUrls = [
                                'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
                                'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css'
                            ];
                            for (var i = 0; i < cssUrls.length; i++) {{
                                try {{
                                    var l = document.createElement('link');
                                    l.rel = 'stylesheet';
                                    l.href = cssUrls[i];
                                    document.head.appendChild(l);
                                }} catch (e) {{}}
                            }}

                            var jsUrls = [
                                'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
                                'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js'
                            ];
                            function loadNext(idx) {{
                                if (typeof window.L !== 'undefined') return;
                                if (idx >= jsUrls.length) return;
                                try {{
                                    var s = document.createElement('script');
                                    s.src = jsUrls[idx];
                                    s.async = true;
                                    s.onload = function() {{ /* ok */ }};
                                    s.onerror = function() {{ loadNext(idx + 1); }};
                                    document.head.appendChild(s);
                                }} catch (e) {{
                                    loadNext(idx + 1);
                                }}
                            }}
                            loadNext(0);
                        }})();
                    </script>
                    <style>
                        html, body {{ margin: 0; height: 100%; }}
                        #map {{ height: 520px; width: 100%; background: #f8fafc; position: relative; overflow: hidden; }}
                        .legend {{
                            position: absolute;
                            top: 10px;
                            left: 10px;
                            z-index: 1000;
                            background: rgba(255,255,255,0.92);
                            padding: 8px 10px;
                            border-radius: 8px;
                            font-family: system-ui;
                            font-size: 12px;
                        }}

                        /* No-JS fallback: static tiles + marker dots */
                        .fb-wrap {{
                            position: absolute;
                            left: 50%;
                            top: 50%;
                            transform: translate(-50%, -50%);
                            width: min(calc(100% - 20px), {fb_width}px);
                            height: min(calc(100% - 20px), {fb_height}px);
                            background: #f8fafc;
                            border-radius: 10px;
                            overflow: hidden;
                            box-shadow: 0 1px 2px rgba(0,0,0,0.10);
                        }}
                        .fb-controls {{
                            position: absolute;
                            top: 10px;
                            right: 10px;
                            z-index: 5;
                            display: flex;
                            gap: 6px;
                            align-items: center;
                            background: rgba(255,255,255,0.92);
                            padding: 6px 8px;
                            border-radius: 10px;
                            font-family: system-ui;
                            font-size: 12px;
                        }}
                        .fb-btn {{
                            width: 28px;
                            height: 28px;
                            border-radius: 8px;
                            border: 1px solid rgba(0,0,0,0.12);
                            background: white;
                            cursor: pointer;
                            font-size: 16px;
                            line-height: 26px;
                        }}
                        .fb-zoom {{ opacity: 0.75; min-width: 56px; text-align: right; }}
                        .fb-viewport {{
                            position: absolute;
                            inset: 0;
                            overflow: hidden;
                            cursor: grab;
                            touch-action: none;
                        }}
                        .fb-viewport:active {{ cursor: grabbing; }}
                        .fb-content {{
                            position: absolute;
                            left: 0;
                            top: 0;
                            width: {fb_width}px;
                            height: {fb_height}px;
                            will-change: transform;
                        }}
                        .fb-zlayer {{ position: absolute; left: 0; top: 0; width: {fb_width}px; height: {fb_height}px; }}
                        .fb-tile {{ position: absolute; width: 256px; height: 256px; }}
                        .fb-tile.fb-missing {{
                            background: repeating-linear-gradient(45deg, #eee, #eee 10px, #f7f7f7 10px, #f7f7f7 20px);
                        }}
                        .fb-marker {{
                            position: absolute;
                            width: 14px;
                            height: 14px;
                            margin-left: -7px;
                            margin-top: -7px;
                            border-radius: 999px;
                            background: #ef4444;
                            border: 2px solid #ffffff;
                            box-shadow: 0 1px 2px rgba(0,0,0,0.25);
                        }}
                    </style>
                </head>
                <body>
                    <div id="map">{fallback_html}</div>
                    <div class=\"legend\"><strong>{title}</strong><br/>{len(locations)} markers</div>

                    <script>
                        var tiles = {tiles_json};
                        var markers = {marker_payload};
                        var allowedZooms = {zoom_levels_json};
                        var boundsByZoom = {bounds_json};
                        var baseUrl = {base_url_json};
                        var fbMeta = {fb_meta_json};
                        var fbMarkersByZoom = {fb_markers_json};

                        function initFallback() {{
                            var root = document.getElementById('fallback');
                            var viewport = document.getElementById('fbViewport');
                            var content = document.getElementById('fbContent');
                            var zoomLabel = document.getElementById('fbZoomLabel');
                            var btnIn = document.getElementById('fbZoomIn');
                            var btnOut = document.getElementById('fbZoomOut');
                            if (!root || !viewport || !content) return;

                            var zoomIdx = 0;
                            for (var i = 0; i < allowedZooms.length; i++) {{
                                if (allowedZooms[i] === {zoom}) {{ zoomIdx = i; break; }}
                            }}

                            var offsetX = 0;
                            var offsetY = 0;
                            var activePointerId = null;
                            var lastX = 0;
                            var lastY = 0;
                            var lastT = 0;
                            var vx = 0;
                            var vy = 0;
                            var inertiaId = 0;
                            var pendingDx = 0;
                            var pendingDy = 0;
                            var rafId = 0;
                            var zoomAnimating = false;

                            function stopInertia() {{
                                if (inertiaId) {{
                                    cancelAnimationFrame(inertiaId);
                                    inertiaId = 0;
                                }}
                            }}

                            function startInertia() {{
                                stopInertia();
                                // Threshold in px/ms. (0.02 => ~0.32px per 16ms frame)
                                if (Math.abs(vx) + Math.abs(vy) < 0.02) return;

                                inertiaId = requestAnimationFrame(function step() {{
                                    inertiaId = 0;
                                    // Apply velocity assuming ~16ms frame.
                                    offsetX += vx * 16;
                                    offsetY += vy * 16;

                                    // Friction.
                                    vx *= 0.92;
                                    vy *= 0.92;

                                    clampOffsets();

                                    if (Math.abs(vx) + Math.abs(vy) >= 0.02) {{
                                        inertiaId = requestAnimationFrame(step);
                                    }}
                                }});
                            }}

                            function clampOffsets() {{
                                var rect = viewport.getBoundingClientRect();
                                var vw = rect.width;
                                var vh = rect.height;
                                var z = String(allowedZooms[zoomIdx]);
                                var meta = fbMeta[z];
                                var lw = meta.width;
                                var lh = meta.height;
                                var minX = Math.min(0, vw - lw);
                                var minY = Math.min(0, vh - lh);
                                if (offsetX > 0) offsetX = 0;
                                if (offsetY > 0) offsetY = 0;
                                if (offsetX < minX) offsetX = minX;
                                if (offsetY < minY) offsetY = minY;
                                content.style.transform = 'translate3d(' + offsetX + 'px,' + offsetY + 'px,0)';
                            }}

                            function scheduleApplyPan() {{
                                if (rafId) return;
                                rafId = requestAnimationFrame(function() {{
                                    rafId = 0;
                                    if (pendingDx || pendingDy) {{
                                        offsetX += pendingDx;
                                        offsetY += pendingDy;
                                        pendingDx = 0;
                                        pendingDy = 0;
                                        clampOffsets();
                                    }}
                                }});
                            }}

                            function render() {{
                                var z = String(allowedZooms[zoomIdx]);
                                var meta = fbMeta[z];
                                if (!meta) return;

                                // Toggle active zoom layer
                                var layers = content.querySelectorAll('.fb-zlayer');
                                for (var i = 0; i < layers.length; i++) {{
                                    var el = layers[i];
                                    el.style.display = (el.getAttribute('data-z') === String(meta.z)) ? 'block' : 'none';
                                }}

                                if (zoomLabel) zoomLabel.textContent = 'z ' + meta.z;
                                clampOffsets();
                            }}

                            function zoomBy(delta) {{
                                stopInertia();
                                var next = zoomIdx + delta;
                                if (next < 0) next = 0;
                                if (next >= allowedZooms.length) next = allowedZooms.length - 1;
                                if (next === zoomIdx) return;

                                // Preserve roughly the same visual center when switching zoom levels.
                                var rect = viewport.getBoundingClientRect();
                                var vw = rect.width;
                                var vh = rect.height;
                                var oldZ = allowedZooms[zoomIdx];
                                var newZ = allowedZooms[next];
                                var factor = Math.pow(2, (newZ - oldZ));
                                offsetX = offsetX * factor - (vw * (factor - 1) / 2);
                                offsetY = offsetY * factor - (vh * (factor - 1) / 2);

                                zoomIdx = next;

                                // Small zoom animation (visual smoothness).
                                try {{
                                    zoomAnimating = true;
                                    content.style.transition = 'transform 120ms ease-out';
                                    setTimeout(function() {{
                                        content.style.transition = '';
                                        zoomAnimating = false;
                                    }}, 160);
                                }} catch (e) {{}}

                                render();
                            }}

                            if (btnIn) btnIn.addEventListener('click', function() {{ zoomBy(1); }});
                            if (btnOut) btnOut.addEventListener('click', function() {{ zoomBy(-1); }});

                            viewport.addEventListener('wheel', function(e) {{
                                stopInertia();
                                // Zoom with wheel; ignore trackpad micro scroll by threshold.
                                if (!e) return;
                                if (Math.abs(e.deltaY) < 2) return;
                                e.preventDefault();
                                zoomBy(e.deltaY < 0 ? 1 : -1);
                            }}, {{ passive: false }});

                            // Pointer events (mouse + touch) for smoother drag.
                            viewport.addEventListener('pointerdown', function(e) {{
                                if (!e) return;
                                stopInertia();
                                try {{ viewport.setPointerCapture(e.pointerId); }} catch (err) {{}}
                                activePointerId = e.pointerId;
                                lastX = e.clientX;
                                lastY = e.clientY;
                                lastT = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
                                vx = 0;
                                vy = 0;
                            }});
                            viewport.addEventListener('pointermove', function(e) {{
                                if (activePointerId === null) return;
                                if (e.pointerId !== activePointerId) return;
                                var dx = e.clientX - lastX;
                                var dy = e.clientY - lastY;
                                lastX = e.clientX;
                                lastY = e.clientY;

                                var now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
                                var dt = Math.max(1, now - lastT);
                                lastT = now;
                                // Low-pass velocity (px/ms).
                                vx = vx * 0.8 + (dx / dt) * 0.2;
                                vy = vy * 0.8 + (dy / dt) * 0.2;

                                pendingDx += dx;
                                pendingDy += dy;
                                scheduleApplyPan();
                            }});
                            viewport.addEventListener('pointerup', function(e) {{
                                if (activePointerId === null) return;
                                if (e.pointerId !== activePointerId) return;
                                activePointerId = null;
                                // Ensure pending pan is applied before momentum starts.
                                scheduleApplyPan();
                                setTimeout(function() {{ startInertia(); }}, 0);
                            }});
                            viewport.addEventListener('pointercancel', function() {{ activePointerId = null; stopInertia(); }});

                            render();
                        }}

                        function start() {{
                            var tries = 0;
                            function tick() {{
                                if (typeof L !== 'undefined') {{
                                    startLeaflet();
                                    return;
                                }}
                                if (tries++ >= 25) {{
                                    initFallback();
                                    return;
                                }}
                                setTimeout(tick, 80);
                            }}
                            tick();
                        }}

                        function startLeaflet() {{
                        try {{
                            var fb = document.getElementById('fallback');
                            if (fb) fb.style.display = 'none';
                        }} catch (e) {{}}

                        function absolutize(url) {{
                            if (!url) return url;
                            if (url.indexOf('http://') === 0 || url.indexOf('https://') === 0) return url;
                            if (baseUrl) return baseUrl + url;
                            return url;
                        }}

                        var dynamicTileTemplate = absolutize('/tiles/{z}/{x}/{y}.png');

                        var map = L.map('map', {{
                            zoomControl: true,
                            scrollWheelZoom: true,
                            doubleClickZoom: true,
                            boxZoom: true,
                            keyboard: true,
                            maxBoundsViscosity: 1.0
                        }}).setView([{center_lat}, {center_lng}], {zoom});

                        var preloadedMinZoom = Math.min.apply(Math, allowedZooms);
                        var preloadedMaxZoom = Math.max.apply(Math, allowedZooms);

                        // Default to the CSP-safe preloaded tiles, then upgrade to dynamic tiles when possible.
                        map.setMinZoom(preloadedMinZoom);
                        map.setMaxZoom(preloadedMaxZoom);
                        map.options.worldCopyJump = true;

                        function applyBoundsForZoom(z) {{
                            var b = boundsByZoom[String(z)];
                            if (!b) return;
                            // boundsByZoom: [west, south, east, north]
                            var sw = L.latLng(b[1], b[0]);
                            var ne = L.latLng(b[3], b[2]);
                            // Important: don't pad outward. Padding increases the allowed view area
                            // beyond the preloaded tiles and causes blank edge tiles.
                            map.setMaxBounds(L.latLngBounds(sw, ne));
                        }}

                        // Preloaded tile layer.
                        var Preloaded = L.GridLayer.extend({{
                            createTile: function(coords) {{
                                var key = coords.z + '/' + coords.x + '/' + coords.y;
                                var img = document.createElement('img');
                                img.width = 256;
                                img.height = 256;
                                img.alt = '';
                                img.referrerPolicy = 'no-referrer';
                                img.style.background = '#f8fafc';
                                if (tiles[key]) {{
                                    img.src = tiles[key];
                                }} else {{
                                    // Tile missing from the preloaded set.
                                    // Keep it blank (transparent) rather than attempting network fetch,
                                    // which is often blocked by host CSP.
                                    img.src = 'data:image/gif;base64,R0lGODlhAQABAAAAACw=';
                                }}
                                return img;
                            }}
                        }});

                        var preloadedLayer = (new Preloaded());
                        preloadedLayer.addTo(map);
                        applyBoundsForZoom(map.getZoom());

                        markers.forEach(function(m) {{
                            var label = m.name;
                            if (m.city) label += ' — ' + m.city;
                            if (m.distance_km !== null && m.distance_km !== undefined) {{
                                label += '<br/><small>' + Number(m.distance_km).toFixed(1) + ' km</small>';
                            }}
                            L.circleMarker([m.lat, m.lng], {{
                                radius: 7,
                                color: '#ffffff',
                                weight: 2,
                                fillColor: '#ef4444',
                                fillOpacity: 0.95
                            }}).addTo(map).bindPopup(label);
                        }});

                        var dynamicEnabled = false;

                        function enableDynamicTiles() {{
                            if (dynamicEnabled) return;
                            dynamicEnabled = true;

                            // Remove bounds and allow full zoom range.
                            try {{
                                map.setMaxBounds(null);
                            }} catch (e) {{
                                // Some builds don't accept null; fall back to world bounds.
                                try {{
                                    map.setMaxBounds(L.latLngBounds(L.latLng(-90, -180), L.latLng(90, 180)));
                                }} catch (e2) {{}}
                            }}
                            map.setMinZoom(0);
                            map.setMaxZoom(19);

                            var tl = L.tileLayer(dynamicTileTemplate, {{
                                maxZoom: 19,
                                attribution: '&copy; OpenStreetMap contributors'
                            }});

                            // Once dynamic tiles are flowing, drop the preloaded layer.
                            tl.once('tileload', function() {{
                                try {{ map.removeLayer(preloadedLayer); }} catch (e) {{}}
                            }});

                            tl.addTo(map);
                        }}

                        function tryEnableDynamicTiles() {{
                            // If the host CSP blocks normal <img> loads (common in ChatGPT srcdoc),
                            // this will error and we'll remain in preloaded mode.
                            var testUrl = dynamicTileTemplate
                                .replace('{z}', '0')
                                .replace('{x}', '0')
                                .replace('{y}', '0');

                            var img = new Image();
                            img.referrerPolicy = 'no-referrer';

                            var done = false;
                            var timer = setTimeout(function() {{
                                if (done) return;
                                done = true;
                            }}, 900);

                            img.onload = function() {{
                                if (done) return;
                                done = true;
                                clearTimeout(timer);
                                enableDynamicTiles();
                            }};
                            img.onerror = function() {{
                                if (done) return;
                                done = true;
                                clearTimeout(timer);
                            }};

                            img.src = testUrl;
                        }}

                        map.on('zoomend', function() {{
                            if (!dynamicEnabled) applyBoundsForZoom(map.getZoom());
                        }});

                        tryEnableDynamicTiles();

                        setTimeout(function() {{ map.invalidateSize(); }}, 250);
                        }}

                        start();
                    </script>
                </body>
                </html>
                """
        )


def _build_map_payload(
    *,
    kind: LocationKind,
    mode: MapMode,
    origin: str | None,
    query: str | None,
    limit: int | None,
    nearest_k: int | None,
    max_km: float | None,
    zoom: int,
    title: str | None,
    tile_url_template: str = "/tiles/{z}/{x}/{y}.png",
) -> dict[str, object]:
    base = _filter_locations(_select_locations(kind), query)
    origin_obj = _parse_origin(origin)

    locations: list[dict[str, object]] = base
    effective_title = title or ("Warehouses" if kind == "warehouse" else "Pharmacies")

    if mode == "nearest":
        if origin_obj is None:
            raise ValueError(
                "Invalid origin. Use a known place name (e.g. 'Pescara') or 'lat,lng' (e.g. '42.46,14.21')."
            )

        o_lat = float(origin_obj["lat"])
        o_lng = float(origin_obj["lng"])

        with_dist: list[dict[str, object]] = []
        for loc in base:
            lat = float(loc["lat"])
            lng = float(loc["lng"])
            d = _haversine_km(o_lat, o_lng, lat, lng)
            if max_km is not None and d > float(max_km):
                continue
            enriched = dict(loc)
            enriched["distance_km"] = round(d, 3)
            with_dist.append(enriched)

        with_dist.sort(key=lambda r: float(r.get("distance_km") or 0.0))

        if nearest_k is not None:
            try:
                k = int(nearest_k)
            except ValueError:
                k = 10
            with_dist = with_dist[: max(0, k)]

        locations = with_dist
        effective_title = f"Nearest {effective_title.lower()}"

    if limit is not None:
        try:
            n = int(limit)
        except ValueError:
            n = 25
        locations = locations[: max(0, n)]

    html = _build_leaflet_html(
        locations=locations,
        zoom=int(zoom),
        title=effective_title,
        tile_url_template=tile_url_template,
    )
    token = _cache_put_html(html)

    return {
        "kind": kind,
        "mode": mode,
        "origin": origin_obj,
        "title": effective_title,
        "locations": locations,
        "map_html": html,
        "map_url": f"/maps/embed/{token}.html",
        "zoom": int(zoom),
    }


def _build_custom_map_payload(
    *,
    locations: list[dict[str, Any]] | None,
    mode: MapMode,
    origin: str | None,
    limit: int | None,
    nearest_k: int | None,
    max_km: float | None,
    zoom: int,
    title: str | None,
    tile_url_template: str = "/tiles/{z}/{x}/{y}.png",
) -> dict[str, object]:
    base = _coerce_custom_locations(locations)
    origin_obj = _parse_origin(origin)

    effective_title = title or "Custom locations"
    out: list[dict[str, object]] = base

    if mode == "nearest":
        if origin_obj is None:
            raise ValueError(
                "Invalid origin. Use a known place name (e.g. 'Pescara') or 'lat,lng' (e.g. '42.46,14.21')."
            )
        o_lat = float(origin_obj["lat"])
        o_lng = float(origin_obj["lng"])

        with_dist: list[dict[str, object]] = []
        for loc in base:
            d = _haversine_km(o_lat, o_lng, float(loc["lat"]), float(loc["lng"]))
            if max_km is not None and d > float(max_km):
                continue
            enriched = dict(loc)
            enriched["distance_km"] = round(d, 3)
            with_dist.append(enriched)
        with_dist.sort(key=lambda r: float(r.get("distance_km") or 0.0))

        if nearest_k is not None:
            try:
                k = int(nearest_k)
            except ValueError:
                k = 10
            with_dist = with_dist[: max(0, k)]

        out = with_dist
        effective_title = f"Nearest {effective_title}"

    if limit is not None:
        try:
            n = int(limit)
        except ValueError:
            n = 25
        out = out[: max(0, n)]

    html = _build_leaflet_html(
        locations=out,
        zoom=int(zoom),
        title=effective_title,
        tile_url_template=tile_url_template,
    )
    token = _cache_put_html(html)
    return {
        "kind": "custom",
        "mode": mode,
        "origin": origin_obj,
        "title": effective_title,
        "locations": out,
        "map_html": html,
        "map_url": f"/maps/embed/{token}.html",
        "zoom": int(zoom),
    }


def register_maps(mcp: FastMCP) -> None:
    """Register map-related tools and routes.

    This is a demo-grade mapping capability intended for showcasing FastMCP apps.
    """

    @mcp.custom_route("/tiles/{z:int}/{x:int}/{y:int}.png", methods=["GET"])
    async def proxy_tile(request):
        z = int(request.path_params["z"])
        x = int(request.path_params["x"])
        y = int(request.path_params["y"])

        if z < _TILE_MIN_Z or z > _TILE_MAX_Z:
            return Response(
                content=_TRANSPARENT_PNG_BYTES,
                media_type="image/png",
                status_code=200,
                headers={"Cache-Control": "no-store"},
            )

        n = 2**z
        x = x % n
        if y < 0 or y >= n:
            return Response(
                content=_TRANSPARENT_PNG_BYTES,
                media_type="image/png",
                status_code=200,
                headers={"Cache-Control": "no-store"},
            )

        key = f"{z}/{x}/{y}"
        cached = _tile_cache_get(key)
        if cached is not None:
            try:
                return Response(
                    content=base64.b64decode(cached),
                    media_type="image/png",
                    status_code=200,
                    headers={"Cache-Control": "public, max-age=1800"},
                )
            except Exception:
                pass

        ip = _client_ip_from_request(request)
        if not _tile_rate_allow(ip):
            return Response(
                content=_TRANSPARENT_PNG_BYTES,
                media_type="image/png",
                status_code=200,
                headers={
                    "Cache-Control": "no-store",
                    "Retry-After": "1",
                },
            )

        try:
            await asyncio.wait_for(_TILE_FETCH_SEM.acquire(), timeout=0.25)
        except TimeoutError:
            return Response(
                content=_TRANSPARENT_PNG_BYTES,
                media_type="image/png",
                status_code=200,
                headers={
                    "Cache-Control": "no-store",
                    "Retry-After": "1",
                },
            )

        try:
            png = await _fetch_osm_tile_png(z, x, y)
            if png is None:
                return Response(
                    content=_TRANSPARENT_PNG_BYTES,
                    media_type="image/png",
                    status_code=200,
                    headers={"Cache-Control": "no-store"},
                )

            return Response(
                content=png,
                media_type="image/png",
                status_code=200,
                headers={"Cache-Control": "public, max-age=1800"},
            )
        finally:
            _TILE_FETCH_SEM.release()

    @mcp.custom_route("/maps/embed/{token:str}.html", methods=["GET"])
    async def map_embed(request):
        token = request.path_params["token"]
        html = _cache_get_html(str(token))

        # ChatGPT (and some enterprise proxies) will refuse to render iframe
        # content if the response sets restrictive framing policies.
        # We explicitly allow framing for this demo embed endpoint.
        headers = {
            "Content-Security-Policy": (
                "default-src * data: blob: 'unsafe-inline' 'unsafe-eval'; "
                "img-src * data: blob:; "
                "style-src * 'unsafe-inline'; "
                "script-src * 'unsafe-inline' 'unsafe-eval'; "
                "connect-src *; "
                "frame-ancestors *"
            ),
            # Some middleware sets XFO=SAMEORIGIN; for a cross-origin embed (ChatGPT),
            # the safest path is to omit XFO entirely. Setting it to an empty value
            # is a pragmatic override in many deployments.
            "X-Frame-Options": "",
        }

        if not html:
            return Response(
                content="<html><body style='font-family:system-ui;padding:12px'>Map expired. Please rebuild.</body></html>",
                media_type="text/html",
                status_code=404,
                headers=headers,
            )
        return Response(content=html, media_type="text/html", status_code=200, headers=headers)

    @mcp.custom_route("/maps/tile/{z:int}/{x:int}/{y:int}.b64", methods=["GET"])
    async def map_tile_b64(request):
        z = int(request.path_params["z"])
        x = int(request.path_params["x"])
        y = int(request.path_params["y"])

        if z < _TILE_MIN_Z or z > _TILE_MAX_Z:
            return Response(
                content=json.dumps({"error": "zoom_out_of_range"}),
                media_type="application/json",
                status_code=400,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        n = 2**z
        x = x % n
        if y < 0 or y >= n:
            return Response(
                content=json.dumps({"b64": None}),
                media_type="application/json",
                status_code=404,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        key = f"{z}/{x}/{y}"
        cached = _tile_cache_get(key)
        if cached is not None:
            return Response(
                content=json.dumps({"b64": cached}),
                media_type="application/json",
                status_code=200,
                headers={
                    "Cache-Control": "public, max-age=1800",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        # Cache miss: protect upstream (OSM) and this server.
        ip = _client_ip_from_request(request)
        if not _tile_rate_allow(ip):
            return Response(
                content=json.dumps({"error": "rate_limited"}),
                media_type="application/json",
                status_code=429,
                headers={
                    "Retry-After": "1",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        # Concurrency cap for upstream fetches.
        try:
            await asyncio.wait_for(_TILE_FETCH_SEM.acquire(), timeout=0.25)
        except TimeoutError:
            return Response(
                content=json.dumps({"error": "busy"}),
                media_type="application/json",
                status_code=429,
                headers={
                    "Retry-After": "1",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        try:
            png = await _fetch_osm_tile_png(z, x, y)
            if png is None:
                return Response(
                    content=json.dumps({"b64": None}),
                    media_type="application/json",
                    status_code=404,
                    headers={"Access-Control-Allow-Origin": "*"},
                )

            b64 = base64.b64encode(png).decode("ascii")
            _tile_cache_put(key, b64)
            return Response(
                content=json.dumps({"b64": b64}),
                media_type="application/json",
                status_code=200,
                headers={
                    "Cache-Control": "public, max-age=1800",
                    "Access-Control-Allow-Origin": "*",
                },
            )
        finally:
            _TILE_FETCH_SEM.release()

    @mcp.tool()
    async def maps_list_known_places() -> list[dict[str, object]]:
        """List built-in demo place names (no external geocoding)."""
        return [
            {"name": name, "lat": lat, "lng": lng}
            for name, (lat, lng) in sorted(KNOWN_PLACES.items())
        ]

    @mcp.tool()
    async def maps_resolve_known_places(names: list[str]) -> dict[str, object]:
        """Resolve a list of place/city names to coordinates using the built-in demo table."""
        resolved: list[dict[str, object]] = []
        missing: list[str] = []

        for raw in names or []:
            if not isinstance(raw, str):
                continue
            key = _normalize_place_key(raw)
            if not key:
                continue

            found = None
            for place, (lat, lng) in KNOWN_PLACES.items():
                if place.lower() == key.lower():
                    found = {"name": place, "lat": lat, "lng": lng}
                    break

            if found is None:
                missing.append(key)
            else:
                resolved.append(found)

        return {"resolved": resolved, "missing": missing}

    @mcp.tool()
    async def maps_list_locations(
        kind: LocationKind = "warehouse",
        query: str | None = None,
        limit: int | str | None = 50,
    ) -> list[dict[str, object]]:
        """List demo locations (warehouses or pharmacies)."""
        locations = _filter_locations(_select_locations(kind), query)
        n = _coerce_optional_int(limit, default=None)
        if n is not None:
            locations = locations[: max(0, n)]
        return locations

    @mcp.tool()
    async def maps_build_map(
        kind: LocationKind = "warehouse",
        mode: MapMode = "all",
        origin: str | None = None,
        query: str | None = None,
        limit: int | str | None = 25,
        nearest_k: int | str | None = 10,
        max_km: float | str | None = None,
        zoom: int | str = 9,
        title: str | None = None,
    ) -> dict[str, object]:
        """Build a map payload (locations + HTML) for embedding in apps.

        - `origin` supports known place names (e.g. "Pescara") or "lat,lng".
        - `mode="nearest"` requires a valid `origin`.
        """

        return _build_map_payload(
            kind=kind,
            mode=mode,
            origin=origin,
            query=query,
            limit=_coerce_optional_int(limit, default=25),
            nearest_k=_coerce_optional_int(nearest_k, default=10),
            max_km=_coerce_optional_float(max_km, default=None),
            zoom=_coerce_optional_int(zoom, default=9) or 9,
            title=_coerce_optional_str(title, default=None),
        )

    @mcp.tool(app=True)
    async def maps_show_map(
        kind: LocationKind = "warehouse",
        mode: MapMode = "all",
        origin: str | None = None,
        query: str | None = None,
        limit: int | str | None = 25,
        nearest_k: int | str | None = 10,
        max_km: float | str | None = None,
        zoom: int | str = 9,
        title: str | None = None,
        ctx: Context | None = None,
    ) -> PrefabApp:
        """Open an interactive map UI.

        This is useful when an LLM wants to *show* results instead of returning plain JSON.
        """

        payload = _build_map_payload(
            kind=kind,
            mode=mode,
            origin=origin,
            query=query,
            limit=_coerce_optional_int(limit, default=25),
            nearest_k=_coerce_optional_int(nearest_k, default=10),
            max_km=_coerce_optional_float(max_km, default=None),
            zoom=_coerce_optional_int(zoom, default=9) or 9,
            title=_coerce_optional_str(title, default=None),
        )

        # ChatGPT's sandbox CSP commonly blocks external `img-src` and `frame-src`.
        # Use a static tile mosaic (data: URIs) for reliable map detail.
        zoom_int = _clamp_zoom(int(payload["zoom"]))
        map_html = await _build_leaflet_preloaded_tiles_html(
            locations=payload["locations"] if isinstance(payload.get("locations"), list) else [],
            zoom=zoom_int,
            title=str(payload["title"]),
            grid=3,
            zoom_span=3,
            base_url=_public_base_url_from_ctx(ctx),
        )

        locations = payload["locations"]
        resolved_origin = payload["origin"]

        with PrefabApp() as app:
            with Column(gap=4, css_class="p-6"):
                Heading(str(payload["title"]))
                Muted(f"{len(locations) if isinstance(locations, list) else 0} locations")

                if isinstance(resolved_origin, dict):
                    with Row(gap=2, align="center"):
                        Badge("Origin", variant="secondary")
                        Badge(str(resolved_origin.get("name") or ""), variant="outline")
                        Badge("Lat", variant="secondary")
                        Badge(str(resolved_origin.get("lat") or ""), variant="outline")
                        Badge("Lng", variant="secondary")
                        Badge(str(resolved_origin.get("lng") or ""), variant="outline")

                with Card():
                    Embed(
                        html=str(map_html),
                        width="100%",
                        height="500px",
                        sandbox="allow-scripts allow-same-origin",
                    )

                DataTable(
                    columns=[
                        DataTableColumn(key="id", header="ID"),
                        DataTableColumn(key="name", header="Name"),
                        DataTableColumn(key="city", header="City"),
                        DataTableColumn(key="kind", header="Kind"),
                        DataTableColumn(key="distance_km", header="Distance km"),
                        DataTableColumn(key="lat", header="Lat"),
                        DataTableColumn(key="lng", header="Lng"),
                    ],
                    rows=locations if isinstance(locations, list) else [],
                    search=True,
                    paginated=True,
                    page_size=15,
                )

        return app

    @mcp.tool(app=True)
    async def maps_show_custom_locations(
        locations: list[dict[str, Any]],
        mode: MapMode = "all",
        origin: str | None = None,
        limit: int | str | None = 50,
        nearest_k: int | str | None = 10,
        max_km: float | str | None = None,
        zoom: int | str = 9,
        title: str | None = None,
        ctx: Context | None = None,
    ) -> PrefabApp:
        """Open an interactive map for caller-supplied locations.

        Intended usage: an LLM (or operator) gathers locations from *any* source
        (patients, inventory, external APIs) and passes them here.

        Each location should ideally include: {name, lat, lng}. If only {city}
        is provided and matches `KNOWN_PLACES`, it will be resolved.
        """

        payload = _build_custom_map_payload(
            locations=locations,
            mode=mode,
            origin=origin,
            limit=_coerce_optional_int(limit, default=50),
            nearest_k=_coerce_optional_int(nearest_k, default=10),
            max_km=_coerce_optional_float(max_km, default=None),
            zoom=_coerce_optional_int(zoom, default=9) or 9,
            title=_coerce_optional_str(title, default=None),
        )

        zoom_int = _clamp_zoom(int(payload["zoom"]))
        map_html = await _build_leaflet_preloaded_tiles_html(
            locations=payload["locations"] if isinstance(payload.get("locations"), list) else [],
            zoom=zoom_int,
            title=str(payload["title"]),
            grid=3,
            zoom_span=3,
            base_url=_public_base_url_from_ctx(ctx),
        )

        resolved_origin = payload["origin"]
        rows = payload["locations"]

        with PrefabApp() as app:
            with Column(gap=4, css_class="p-6"):
                Heading(str(payload["title"]))
                Muted(f"{len(rows) if isinstance(rows, list) else 0} mappable locations")

                if isinstance(resolved_origin, dict):
                    with Row(gap=2, align="center"):
                        Badge("Origin", variant="secondary")
                        Badge(str(resolved_origin.get("name") or ""), variant="outline")

                with Card():
                    Embed(
                        html=str(map_html),
                        width="100%",
                        height="500px",
                        sandbox="allow-scripts allow-same-origin",
                    )

                DataTable(
                    columns=[
                        DataTableColumn(key="id", header="ID"),
                        DataTableColumn(key="name", header="Name"),
                        DataTableColumn(key="city", header="City"),
                        DataTableColumn(key="kind", header="Kind"),
                        DataTableColumn(key="distance_km", header="Distance km"),
                        DataTableColumn(key="lat", header="Lat"),
                        DataTableColumn(key="lng", header="Lng"),
                    ],
                    rows=rows if isinstance(rows, list) else [],
                    search=True,
                    paginated=True,
                    page_size=15,
                )

        return app

    @mcp.tool(app=True)
    async def maps_show_custom_locations_from_json(
        locations_json: str,
        mode: MapMode = "all",
        origin: str | None = None,
        limit: int | str | None = 50,
        nearest_k: int | str | None = 10,
        max_km: float | str | None = None,
        zoom: int | str = 9,
        title: str | None = None,
        ctx: Context | None = None,
    ) -> PrefabApp:
        """Open an interactive map for caller-supplied locations encoded as JSON.

        Accepts either:
        - a JSON list: `[{"name": "...", "lat": 1.23, "lng": 4.56}, ...]`
        - or a JSON object with a `locations` key: `{ "locations": [...] }`
        """

        try:
            parsed = json.loads(locations_json or "")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for locations: {e.msg}")

        if isinstance(parsed, dict) and "locations" in parsed:
            parsed_locations = parsed.get("locations")
        else:
            parsed_locations = parsed

        if not isinstance(parsed_locations, list):
            raise ValueError("locations_json must decode to a list (or an object with a 'locations' list)")

        locations = [x for x in parsed_locations if isinstance(x, dict)]
        if not locations:
            raise ValueError("No valid locations found. Provide a non-empty JSON list of objects with lat/lng (or resolvable city).")

        payload = _build_custom_map_payload(
            locations=locations,
            mode=mode,
            origin=origin,
            limit=_coerce_optional_int(limit, default=50),
            nearest_k=_coerce_optional_int(nearest_k, default=10),
            max_km=_coerce_optional_float(max_km, default=None),
            zoom=_coerce_optional_int(zoom, default=9) or 9,
            title=_coerce_optional_str(title, default=None),
        )

        zoom_int = _clamp_zoom(int(payload["zoom"]))
        map_html = await _build_leaflet_preloaded_tiles_html(
            locations=payload["locations"] if isinstance(payload.get("locations"), list) else [],
            zoom=zoom_int,
            title=str(payload["title"]),
            grid=3,
            zoom_span=3,
            base_url=_public_base_url_from_ctx(ctx),
        )

        resolved_origin = payload["origin"]
        rows = payload["locations"]

        with PrefabApp() as app:
            with Column(gap=4, css_class="p-6"):
                Heading(str(payload["title"]))
                Muted(f"{len(rows) if isinstance(rows, list) else 0} mappable locations")

                if isinstance(resolved_origin, dict):
                    with Row(gap=2, align="center"):
                        Badge("Origin", variant="secondary")
                        Badge(str(resolved_origin.get("name") or ""), variant="outline")

                with Card():
                    Embed(
                        html=str(map_html),
                        width="100%",
                        height="500px",
                        sandbox="allow-scripts allow-same-origin",
                    )

                DataTable(
                    columns=[
                        DataTableColumn(key="id", header="ID"),
                        DataTableColumn(key="name", header="Name"),
                        DataTableColumn(key="city", header="City"),
                        DataTableColumn(key="kind", header="Kind"),
                        DataTableColumn(key="distance_km", header="Distance km"),
                        DataTableColumn(key="lat", header="Lat"),
                        DataTableColumn(key="lng", header="Lng"),
                    ],
                    rows=rows if isinstance(rows, list) else [],
                    search=True,
                    paginated=True,
                    page_size=15,
                )

        return app
