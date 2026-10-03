from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

CARD_EMBED_URI = "ui://lottomaticapss/saved-card.html"
CARD_EMBED_META_KEY = "lottomaticapss/saved-card"
CARD_EMBED_MIME = "text/html;profile=mcp-app"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_card_embed_url(site_url: str, secret: str, card_id: int, *, ttl_seconds: int, now: float | None = None) -> tuple[str, int]:
    """Return a Metabase static-embed URL for a published card and its expiry (epoch seconds)."""
    expires_at = int(now if now is not None else time.time()) + ttl_seconds
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"resource": {"question": card_id}, "params": {}, "exp": expires_at},
                                 separators=(",", ":")).encode())
    signature = _b64url(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{site_url.rstrip('/')}/embed/question/{header}.{payload}.{signature}", expires_at


def card_embed_resource_meta(site_url: str) -> dict[str, Any]:
    origin = site_url.rstrip("/")
    return {
        "ui": {"csp": {"frameDomains": [origin], "connectDomains": [], "resourceDomains": []},
               "domain": origin, "prefersBorder": True},
        "openai/widgetCSP": {"frame_domains": [origin], "connect_domains": [], "resource_domains": []},
        "openai/widgetPrefersBorder": True,
    }


CARD_EMBED_HTML = """<!doctype html>
<html lang="it"><head><meta charset="UTF-8"/><meta name="robots" content="noindex"/>
<title>Ditra Analytics</title>
<style>
  html, body { margin: 0; height: 100%; font-family: system-ui, sans-serif; background: transparent; }
  #frame { display: none; width: 100%; height: 520px; border: 0; }
  #status { display: flex; align-items: center; justify-content: center; height: 520px;
            padding: 0 24px; box-sizing: border-box; text-align: center; color: #696e7b; font-size: 14px; }
</style></head>
<body><div id="status">Connessione in corso…</div><iframe id="frame" title="Ditra Analytics"></iframe>
<script>
(function () {
  var META_KEY = "__META_KEY__", HEIGHT = 520, LOAD_TIMEOUT_MS = 20000;
  var parentWin = window.parent, nextId = 1, pending = {}, hostCaps = {}, dark = false;
  var rendered = false, handled = false, loaded = false;
  var statusEl = document.getElementById("status"), frameEl = document.getElementById("frame");

  function send(msg) { try { parentWin.postMessage(msg, "*"); } catch (e) {} }
  function request(method, params, timeoutMs) {
    var id = nextId++;
    send({ jsonrpc: "2.0", id: id, method: method, params: params });
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      setTimeout(function () { if (pending[id]) { delete pending[id]; reject(new Error("timeout")); } }, timeoutMs);
    });
  }
  function showStatus(text) { frameEl.style.display = "none"; statusEl.style.display = "flex"; statusEl.textContent = text; }
  function showNote(text) {
    showStatus(text);
    statusEl.style.height = "auto"; statusEl.style.padding = "10px 16px"; statusEl.style.justifyContent = "flex-start";
    statusEl.style.textAlign = "left"; statusEl.style.fontSize = "13px";
    send({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: statusEl.offsetHeight || 40 } });
  }
  function embedOf(meta) { return (meta && meta[META_KEY]) || null; }
  function usable(embed) {
    return !!(embed && embed.url && (!embed.expires_at || embed.expires_at * 1000 - Date.now() > 60000));
  }
  function render(url) {
    if (rendered) return;
    rendered = true;
    frameEl.onload = function () { loaded = true; };
    frameEl.src = url.split("#")[0] + "#bordered=false&titled=true" + (dark ? "&theme=night" : "");
    statusEl.style.display = "none"; frameEl.style.display = "block";
    send({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: HEIGHT } });
    setTimeout(function () {
      if (!loaded) showStatus("La visualizzazione non si è caricata. Il client potrebbe bloccare i contenuti incorporati da Ditra Analytics.");
    }, LOAD_TIMEOUT_MS);
  }
  function applyContext(ctx) { if (ctx && ctx.theme) { dark = ctx.theme === "dark"; } }

  function handleResult(structured, meta, text) {
    if (handled) return;
    var sc = structured || {};
    if (!sc.card_id) return;
    handled = true;
    if (!sc.published) {
      showNote("\u2139\ufe0f " + (sc.name ? "\u201c" + sc.name + "\u201d " : "") +
        "non \u00e8 pubblicata con la visualizzazione salvata: segue il grafico interattivo automatico.");
      return;
    }
    var initial = embedOf(meta);
    if (usable(initial)) { render(initial.url); return; }
    showStatus("Apertura della visualizzazione salvata…");
    request("tools/call", { name: "saved_card_embed_url", arguments: { card_id: sc.card_id } }, 10000)
      .then(function (r) {
        var fresh = embedOf(r && r._meta);
        if (fresh && fresh.url) render(fresh.url); else throw new Error("no url");
      })
      .catch(function () { showStatus("Il collegamento alla visualizzazione è scaduto. Richiedi di nuovo il grafico."); });
  }
  function fromToolResult(params) {
    var text = params && params.content && params.content[0] && params.content[0].text;
    handleResult(params && params.structuredContent, params && params._meta, text);
  }
  function fromOpenAi() {
    var oa = window.openai;
    if (oa && oa.toolOutput) handleResult(oa.toolOutput, oa.toolResponseMetadata, null);
  }

  window.addEventListener("message", function (ev) {
    if (ev.source !== parentWin) return;
    var m = ev.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id !== undefined && !m.method) {
      var p = pending[m.id];
      if (p) { delete pending[m.id]; m.error ? p.reject(m.error) : p.resolve(m.result); }
      return;
    }
    if (m.method === "ui/notifications/tool-result") {
      fromToolResult(m.params);
    } else if (m.method === "ui/notifications/host-context-changed") {
      applyContext(m.params);
    } else if (m.id !== undefined && m.method) {
      send({ jsonrpc: "2.0", id: m.id, result: {} });
    }
  });
  window.addEventListener("openai:set_globals", fromOpenAi);
  fromOpenAi();

  request("ui/initialize", {
    appInfo: { name: "lottomaticapss-saved-card", version: "1.1.0" },
    appCapabilities: {},
    protocolVersion: "2026-01-26"
  }, 5000).then(function (r) {
    hostCaps = (r && r.hostCapabilities) || {};
    applyContext(r && r.hostContext);
  }).catch(function () {}).then(function () {
    send({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} });
    if (!handled) statusEl.textContent = "Caricamento visualizzazione…";
    fromOpenAi();
  });
})();
</script></body></html>
""".replace("__META_KEY__", CARD_EMBED_META_KEY)
