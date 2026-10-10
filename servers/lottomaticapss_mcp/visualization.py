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


def saved_chart_payload(card: Any, result: Any, *, row_limit: int = 1000) -> dict[str, Any]:
    """Build a bounded, data-only payload for the authenticated ECharts widget."""
    if not isinstance(card, dict) or not isinstance(result, dict):
        raise ValueError("Saved question metadata or result is invalid")
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    columns = data.get("cols")
    rows = data.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("Saved question returned no tabular chart data")
    return {
        "card_id": card.get("id"),
        "title": card.get("name") or f"Card {card.get('id')}",
        "display": card.get("display"),
        "settings": card.get("visualization_settings") or {},
        "columns": columns,
        "rows": rows[:row_limit],
        "row_count": len(rows),
        "truncated": len(rows) > row_limit,
    }


def saved_card_table_payload(card: Any, result: Any) -> dict[str, Any]:
    if not isinstance(card, dict) or not isinstance(result, dict):
        raise ValueError("Saved question metadata or result is invalid")
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    columns, rows = data.get("cols"), data.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("Saved question returned no tabular data")
    if any(not isinstance(column, dict) for column in columns):
        raise ValueError("Saved question returned invalid columns")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError("Saved question returned invalid rows")
    visible_rows = []
    cells_truncated = False
    for row in rows[:50]:
        visible_row = []
        for value in row[:30]:
            if not isinstance(value, (str, int, float, bool, type(None))):
                value = json.dumps(value, ensure_ascii=True)
            if isinstance(value, str):
                cells_truncated = cells_truncated or len(value) > 160
                value = value[:160]
            visible_row.append(value)
        visible_rows.append(visible_row)
    return {
        "card_id": card.get("id"),
        "title": str(card.get("name") or f"Card {card.get('id')}")[:160],
        "saved_display": card.get("display"),
        "renderer": "table",
        "columns": [str(column.get("display_name") or column.get("name") or "Column")[:160] for column in columns[:30]],
        "rows": visible_rows,
        "row_count": len(rows),
        "column_count": len(columns),
        "truncated": len(rows) > 50 or len(columns) > 30 or cells_truncated,
    }
