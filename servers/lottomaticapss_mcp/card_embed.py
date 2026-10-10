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
ECHARTS_CARD_URI = "ui://ditra_analytics/metabase/echarts-saved-card.html"
ECHARTS_CARD_META_KEY = "lottomaticapss/echarts-card"
ECHARTS_CDN_INTEGRITY = "sha384-pPi0zxBAoDu6+JXW/C68UZLvBUUtU+7zonhif43rqj7pxsGyqyqzcian2Rj37Rss"


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


ECHARTS_CARD_RESOURCE_META = {
    "ui": {
        "domain": "https://analytics.ditra.io",
        "csp": {"connectDomains": [], "resourceDomains": ["https://cdn.jsdelivr.net"]},
        "prefersBorder": True,
    }
}


ECHARTS_CARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ditra Analytics</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js" integrity="__INTEGRITY__" crossorigin="anonymous"></script>
<style>html,body,#chart{margin:0;width:100%;height:100%;min-height:360px}body{font:14px system-ui,sans-serif;color:#242a33}#status{padding:20px}</style></head>
<body><div id="status">Loading saved chart…</div><div id="chart" role="img" aria-label="Saved Ditra Analytics chart" hidden></div>
<script>
(function(){
  var KEY="__META_KEY__", parent=window.parent, id=1, pending={}, chart=null, rendered=false;
  function send(message){parent.postMessage(message,"*");}
  function request(method,params){var requestId=id++;send({jsonrpc:"2.0",id:requestId,method:method,params:params});return new Promise(function(resolve,reject){pending[requestId]={resolve:resolve,reject:reject};setTimeout(function(){if(pending[requestId]){delete pending[requestId];reject(new Error("Host request timed out"));}},5000);});}
  function columnIndex(columns,names){for(var i=0;i<columns.length;i++){var column=columns[i]||{};if(names.indexOf(column.name)>=0||names.indexOf(column.display_name)>=0)return i;}return -1;}
  function number(value){if(value===null||value===undefined||value==="")return null;var parsed=Number(value);return Number.isFinite(parsed)?parsed:null;}
  function render(payload){if(rendered||!payload||!Array.isArray(payload.rows)||!Array.isArray(payload.columns))return;rendered=true;
    var settings=payload.settings||{},dimensions=settings["graph.dimensions"]||[],metrics=settings["graph.metrics"]||[],display=payload.display;
    var dimIndex=columnIndex(payload.columns,dimensions),metricIndexes=metrics.map(function(metric){return columnIndex(payload.columns,[metric]);}).filter(function(index){return index>=0;});
    if(dimIndex<0)dimIndex=0;
    if(!metricIndexes.length){metricIndexes=payload.columns.map(function(column,index){return {column:column,index:index};}).filter(function(entry){return entry.index!==dimIndex&&/number|integer|float|decimal|bigint/i.test(String(entry.column.base_type||entry.column.semantic_type||""));}).map(function(entry){return entry.index;});}
    if(!metricIndexes.length){document.getElementById("status").textContent="No numeric series is available for this saved chart.";return;}
    var xName=payload.columns[dimIndex].display_name||payload.columns[dimIndex].name||"Category";
    var timeAxis=settings["graph.x_axis.scale"]==="timeseries";
    var xValues=payload.rows.map(function(row){var value=row[dimIndex];return timeAxis&&typeof value==="string"?Date.parse(value):value;});
    var secondDimIndex=display==="combo"&&dimensions.length>1?columnIndex(payload.columns,dimensions.slice(1,2)):-1;
    var seriesSettings=settings.series_settings||{};
    var groups=secondDimIndex>=0?Array.from(new Set(payload.rows.map(function(row){return String(row[secondDimIndex]??"");}))):[];
    function makeSeries(index,group){
      var column=payload.columns[index]||{}, metricName=column.display_name||column.name||"Value";
      var seriesName=group===null?metricName:(metricIndexes.length>1?group+" · "+metricName:group);
      var style=(settings.column_settings||{})[JSON.stringify(["name",column.name])]||{};
      var scale=Number(style.scale)||1;
      var selectedRows=group===null?payload.rows:payload.rows.filter(function(row){return String(row[secondDimIndex]??"")===group;});
      var points=selectedRows.map(function(row){var rowIndex=payload.rows.indexOf(row),value=number(row[index]);return [xValues[rowIndex],value===null?null:value*scale];});
      var savedSeries=group===null?{}:(seriesSettings[group]||{});
      var seriesType=savedSeries.display|| (display==="bar"?"bar":"line");
      var item={name:seriesName,type:seriesType==="area"?"line":seriesType,data:points,smooth:settings["graph.smooth"]===true,label:{show:settings["graph.show_values"]===true,position:"top"}};
      if(display==="area")item.areaStyle={opacity:0.28};
      if(seriesType==="area")item.areaStyle={opacity:0.28};
      return item;
    }
    var series=groups.length?groups.flatMap(function(group){return metricIndexes.map(function(index){return makeSeries(index,group);});}):metricIndexes.map(function(index){return makeSeries(index,null);});
    var firstColumn=payload.columns[metricIndexes[0]]||{}, firstStyle=(settings.column_settings||{})[JSON.stringify(["name",firstColumn.name])]||{};
    var decimals=Number.isInteger(firstStyle.decimals)?firstStyle.decimals:0;
    var formatter=function(value){return (firstStyle.prefix||"")+Number(value).toFixed(decimals)+(firstStyle.suffix||"");};
    var option={animation:false,color:settings["graph.colors"],title:{text:payload.title,left:"center"},tooltip:{trigger:"axis",renderMode:"richText"},legend:{type:"scroll",top:32},grid:{left:56,right:24,top:76,bottom:56,containLabel:true},xAxis:{type:timeAxis?"time":"category",name:xName,data:timeAxis?undefined:xValues,axisLabel:{show:settings["graph.x_axis.labels_enabled"]!==false,hideOverlap:true}},yAxis:{type:"value",axisLabel:{show:settings["graph.y_axis.labels_enabled"]!==false,formatter:formatter}},series:series};
    if(display==="pie"){
      var categories=payload.rows.map(function(row){return String(row[dimIndex]??"");});
      option={animation:false,title:{text:payload.title,left:"center"},tooltip:{trigger:"item",renderMode:"richText"},legend:{type:"scroll",bottom:0},series:[{type:"pie",radius:["0%","66%"],data:payload.rows.map(function(row,index){return {name:categories[index],value:number(row[metricIndexes[0]])};})}]};
    }else if(!["area","line","bar","combo"].includes(display)){
      document.getElementById("status").textContent="ECharts does not yet support the saved '"+String(display)+"' visualization type.";return;
    }
    document.getElementById("status").hidden=true;var element=document.getElementById("chart");element.hidden=false;chart=echarts.init(element);chart.setOption(option);window.addEventListener("resize",function(){if(chart)chart.resize();});
    if(payload.truncated){var note=document.createElement("p");note.textContent="Showing the first "+payload.rows.length+" of "+payload.row_count+" rows.";document.body.appendChild(note);}
    send({jsonrpc:"2.0",method:"ui/notifications/size-changed",params:{height:Math.max(400,element.scrollHeight)}});
  }
  function receiveResult(params){var metadata=params&&params._meta, payload=metadata&&metadata[KEY];render(payload);}
  function fromHost(){var host=window.openai;if(host&&host.toolResponseMetadata)render(host.toolResponseMetadata[KEY]);}
  window.addEventListener("message",function(event){if(event.source!==parent)return;var message=event.data;if(!message||message.jsonrpc!=="2.0")return;
    if(message.id!==undefined&&!message.method){var entry=pending[message.id];if(entry){delete pending[message.id];message.error?entry.reject(message.error):entry.resolve(message.result);}return;}
    if(message.method==="ui/notifications/tool-result")receiveResult(message.params);
    else if(message.id!==undefined&&message.method)send({jsonrpc:"2.0",id:message.id,result:{}});
  });
  window.addEventListener("openai:set_globals",fromHost);
  request("ui/initialize",{appInfo:{name:"ditra-echarts-saved-card",version:"1.0.0"},appCapabilities:{},protocolVersion:"2026-01-26"}).then(function(){send({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}});fromHost();}).catch(function(){document.getElementById("status").textContent="The chart renderer could not connect to ChatGPT.";});
})();
</script></body></html>
""".replace("__INTEGRITY__", ECHARTS_CDN_INTEGRITY).replace("__META_KEY__", ECHARTS_CARD_META_KEY)
