from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _plain_date_literals(node: Any) -> Any:
    if isinstance(node, list):
        if (
            len(node) == 4
            and node[0] == "absolute-datetime"
            and isinstance(node[1], dict)
            and isinstance(node[2], str)
            and _DATE_ONLY.match(node[2])
            and node[3] == "day"
        ):
            return node[2]
        return [_plain_date_literals(item) for item in node]
    if isinstance(node, dict):
        return {key: _plain_date_literals(value) for key, value in node.items()}
    return node


def repair_visualization_payload(structured: Any) -> dict[str, Any] | None:
    """Return a repaired visualize_query payload, or None when nothing needs changing.

    Metabase's construct_query rewrites saved date filters to absolute-datetime clauses that
    its own query processor rejects (500 "truncate-to ... java.lang.String"), which the
    MCP Apps renderer shows as "Question not found".
    """
    if not isinstance(structured, dict) or not isinstance(structured.get("query"), str):
        return None
    try:
        query = json.loads(base64.b64decode(structured["query"], validate=True).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    repaired = _plain_date_literals(query)
    if repaired == query:
        return None
    encoded = base64.b64encode(json.dumps(repaired, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return {**structured, "query": encoded}
