from __future__ import annotations

import re

BRAND_NAME = "Ditra Analytics"
_MARKER = "<!-- ditra-analytics-white-label -->"

# Skips URLs/identifiers (metabase.com, window.Metabase, metabase-mcp) but brands sentence-final "Metabase.".
BRAND_FUNCTION_JS = (
    "function brand(s){return s.replace("
    r"/(^|[^\w.\/@-])[Mm]etabase(?![\w\/:@-]|\.\w)/g,"
    f'function(_,p){{return p+"{BRAND_NAME}";}});}}'
)

_OBSERVER_JS = (
    "(function(){" + BRAND_FUNCTION_JS +
    'var ATTRS=["title","aria-label","placeholder","alt"];'
    "var SKIP={SCRIPT:1,STYLE:1,TEXTAREA:1,NOSCRIPT:1};"
    "function fixText(n){var p=n.parentNode;if(!p||SKIP[p.nodeName]||p.isContentEditable)return;"
    "var v=n.nodeValue,b=brand(v);if(b!==v)n.nodeValue=b;}"
    "function fixEl(el){if(!el.getAttribute)return;for(var i=0;i<ATTRS.length;i++){"
    "var a=el.getAttribute(ATTRS[i]);if(a){var b=brand(a);if(b!==a)el.setAttribute(ATTRS[i],b);}}}"
    "function walk(root){if(root.nodeType===3){fixText(root);return;}"
    "if(root.nodeType!==1&&root.nodeType!==11)return;if(root.nodeType===1){if(SKIP[root.nodeName])return;fixEl(root);}"
    "var w=document.createTreeWalker(root,5,null),n;while((n=w.nextNode())){if(n.nodeType===3)fixText(n);else fixEl(n);}}"
    "function fixTitle(){var t=document.title,b=brand(t);if(b!==t)document.title=b;}"
    "new MutationObserver(function(ms){for(var i=0;i<ms.length;i++){var m=ms[i];"
    'if(m.type==="characterData")fixText(m.target);else if(m.type==="attributes")fixEl(m.target);'
    "else for(var j=0;j<m.addedNodes.length;j++)walk(m.addedNodes[j]);}fixTitle();})"
    ".observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:ATTRS});"
    "walk(document.documentElement);fixTitle();})();"
)

_HEAD_OPEN = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
_TITLE = re.compile(r"<title>\s*Metabase\s*</title>", re.IGNORECASE)


def white_label_analytics_renderer(html: str) -> str:
    """Replace user-visible Metabase branding in the Ditra Analytics MCP Apps renderer."""
    if _MARKER in html:
        return html
    html = _TITLE.sub(f"<title>{BRAND_NAME}</title>", html)
    script = f"{_MARKER}<script>{_OBSERVER_JS}</script>"
    match = _HEAD_OPEN.search(html)
    if match is None:
        return script + html
    return html[: match.end()] + script + html[match.end():]
