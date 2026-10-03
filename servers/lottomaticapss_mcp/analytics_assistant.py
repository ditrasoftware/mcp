"""Ditra Analytics KPI answering layer for Lottomatica PSS.

Turns a business question such as "ordinato lordo IVA di Novaconnect nei primi
6 mesi del 2025" into a verified Metabase query:

* canonical source selection (ODA detail model by default),
* metric / entity-field / timeframe resolution with confidence scores,
* typed MBQL generation (REST legacy MBQL and MBQL 5) plus validation/dry-run,
* native-SQL permission preflight and saved-question parameter introspection,
* an execution fallback chain that always reports what ran and why.

All Metabase calls go through the REST API identity of `MetabaseClient`.
"""

from __future__ import annotations

import asyncio
import copy
import difflib
import json
import re
import time
import unicodedata
import uuid
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .metabase_client import MetabaseClient, MetabaseClientError


class KpiError(RuntimeError):
    """Invalid KPI input or a failed Metabase query."""

    def __init__(self, message: str, *, error_type: str | None = None):
        super().__init__(message)
        self.error_type = error_type


NUMERIC_TYPES = frozenset(
    {
        "type/Decimal",
        "type/Float",
        "type/Integer",
        "type/BigInteger",
        "type/Number",
        "type/Currency",
    }
)
TEMPORAL_TYPES = frozenset(
    {
        "type/Date",
        "type/DateTime",
        "type/DateTimeWithLocalTZ",
        "type/DateTimeWithTZ",
        "type/DateTimeWithZoneOffset",
        "type/Instant",
    }
)
TEXT_TYPES = frozenset({"type/Text", "type/Category", "type/TextLike"})
TEMPORAL_UNITS = ("day", "week", "month", "quarter", "year")
# Aggregation -> whether a field argument is required.
AGGREGATIONS = {"sum": True, "avg": True, "min": True, "max": True, "distinct": True, "count": False}
ADDITIVE_AGGREGATIONS = frozenset({"sum", "count"})
# Filter operator -> (min values, max values or None for unbounded).
FILTER_ARITY: dict[str, tuple[int, int | None]] = {
    "=": (1, None),
    "!=": (1, None),
    "<": (1, 1),
    ">": (1, 1),
    "<=": (1, 1),
    ">=": (1, 1),
    "between": (2, 2),
    "contains": (1, 1),
    "does-not-contain": (1, 1),
    "starts-with": (1, 1),
    "ends-with": (1, 1),
    "is-null": (0, 0),
    "not-null": (0, 0),
}
STRING_OPS = frozenset({"contains", "does-not-contain", "starts-with", "ends-with"})
LOGICAL_OPS = frozenset({"and", "or", "not"})
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)
_CARD_SOURCE = re.compile(r"^card__(\d+)$")


# -- Canonical source registry --------------------------------------------------

KNOWN_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "kind": "card",
        "id": 685,
        "name": "model_zrep_oda_detail",
        "role": "canonical",
        "date_field": "oda_date_for_filter",
        "default_filters": [
            {
                "field": "is_pss_order",
                "op": "=",
                "values": [1],
                "reason": "PSS orders only, as in card 840 'Ordinato per Mese'",
            }
        ],
        "notes": (
            "Row-level SAP ZREP ODA detail model; *_EURO amounts are normalised "
            "to EUR. Backs card 840 'Ordinato per Mese'."
        ),
    },
    {"kind": "card", "id": 469, "name": "model_zrep_oda", "role": "alternative",
     "notes": "ODA model; evaluate before use for KPI totals."},
    {"kind": "card", "id": 722, "name": "model_zrep_oda_kpi", "role": "alternative",
     "notes": "ODA KPI model; evaluate before use for KPI totals."},
    {"kind": "card", "id": 847, "name": "model_zrep_oda_combined", "role": "alternative",
     "notes": "Combined ODA model; evaluate before use for KPI totals."},
    {"kind": "card", "id": 109, "name": "ZREP ODA Analysis", "role": "analysis_question",
     "notes": "Saved analysis question, not a KPI base."},
    {"kind": "table", "id": 52, "name": "zrep_oda", "role": "raw_table",
     "notes": "Raw synced table; the EUR-normalised *_EURO fields exist only in the models."},
)


@dataclass(frozen=True)
class SourceField:
    name: str
    base_type: str
    display_name: str | None = None
    semantic_type: str | None = None
    id: int | None = None


@dataclass
class KpiSource:
    kind: str
    id: int
    name: str
    database_id: int
    database_name: str | None
    entity_id: str | None
    source_type: str | None
    fields: list[SourceField]
    role: str = "candidate"
    date_field: str | None = None
    default_filters: list[dict[str, Any]] = field(default_factory=list)
    notes: str | None = None

    def get_field(self, name: str) -> SourceField | None:
        for item in self.fields:
            if item.name == name:
                return item
        folded = _fold(name).strip()
        for item in self.fields:
            if _fold(item.name).strip() == folded or (
                item.display_name and _fold(item.display_name).strip() == folded
            ):
                return item
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "type": self.source_type,
            "database_id": self.database_id,
            "role": self.role,
        }


# -- Text helpers ---------------------------------------------------------------

_ABBREVIATIONS = {
    "ord": "ordinato",
    "qt": "quantita",
    "tot": "totale",
    "imp": "importo",
    "doc": "documento",
    "acq": "acquisti",
    "descr": "descrizione",
}
_STOPWORDS = frozenset(
    "a al alla allo ai il lo la i gli le di del della dello dei degli delle da dal "
    "dalla nel nella nei negli in per su con e o the of for on to by me show mostra "
    "mostrami dammi fammi vedere quanto quanti quale qual".split()
)
_CURRENCY = frozenset({"euro", "eur"})
_LEGAL_SUFFIXES = frozenset(
    {"srl", "srls", "spa", "sas", "snc", "sapa", "scarl", "scrl", "ltd", "gmbh", "inc", "llc", "bv", "ag", "sa"}
)


def _fold(text: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _words(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(text))


def _tokens(text: Any) -> list[str]:
    return [_ABBREVIATIONS.get(w, w) for w in _words(text) if w not in _STOPWORDS]


def _norm_name(text: Any) -> str:
    return " ".join(_words(text))


def _core_name(text: Any) -> str:
    """Alphanumeric company name without trailing legal-form suffixes."""
    words = _words(text)
    changed = True
    while changed and words:
        changed = False
        for size in (3, 2, 1):
            if len(words) > size and "".join(words[-size:]) in _LEGAL_SUFFIXES:
                words = words[:-size]
                changed = True
                break
    return "".join(words)


def similarity(a: Any, b: Any) -> float:
    ca, cb = _core_name(a), _core_name(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if ca in cb or cb in ca:
        return round(0.75 + 0.2 * min(len(ca), len(cb)) / max(len(ca), len(cb)), 3)
    return round(difflib.SequenceMatcher(None, ca, cb).ratio(), 3)


# -- Timeframes -----------------------------------------------------------------


@dataclass(frozen=True)
class Timeframe:
    start: date
    end: date
    label: str

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label}


_ORDINALS = {
    "primo": 1, "prima": 1, "1o": 1, "first": 1, "1st": 1,
    "secondo": 2, "seconda": 2, "2o": 2, "second": 2, "2nd": 2,
    "terzo": 3, "terza": 3, "3o": 3, "third": 3, "3rd": 3,
    "quarto": 4, "quarta": 4, "4o": 4, "fourth": 4, "4th": 4,
}
_ORDINAL_RE = "|".join(sorted(_ORDINALS, key=len, reverse=True))
_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_RE = "|".join(_MONTHS)
_OF = r"(?:\s+(?:del|dell|dello|of|in|nel))?\s*(?:anno\s+)?"


def _span(year: int, first_month: int, months: int, label: str) -> Timeframe:
    last = first_month + months - 1
    return Timeframe(date(year, first_month, 1), date(year, last, monthrange(year, last)[1]), label)


def parse_timeframe(text: Any, *, strict: bool = True) -> Timeframe | None:
    """Parse ISO ranges, years, halves, quarters, months and Italian/English phrases."""

    if text is None or not str(text).strip():
        return None
    raw = str(text).strip()
    folded = _fold(raw).replace("°", "o").replace("º", "o").replace("'", " ")
    try:
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", folded)
        if len(dates) >= 2:
            start, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[1])
            if end < start:
                raise KpiError("Timeframe end date precedes its start date", error_type="invalid_timeframe")
            return Timeframe(start, end, f"{start.isoformat()}..{end.isoformat()}")
        if len(dates) == 1:
            day = date.fromisoformat(dates[0])
            return Timeframe(day, day, day.isoformat())

        m = re.search(r"\b(?:primi|first)\s+(\d{1,2})\s+(?:mesi|months)\b" + _OF + r"(\d{4})\b", folded)
        if m and 1 <= int(m.group(1)) <= 12:
            n, year = int(m.group(1)), int(m.group(2))
            return _span(year, 1, n, f"{year} first {n} months")
        m = re.search(r"\b(?:ultimi|last)\s+(\d{1,2})\s+(?:mesi|months)\b" + _OF + r"(\d{4})\b", folded)
        if m and 1 <= int(m.group(1)) <= 12:
            n, year = int(m.group(1)), int(m.group(2))
            return _span(year, 13 - n, n, f"{year} last {n} months")
        m = re.search(rf"\b({_ORDINAL_RE})\s+(?:semestre|half)\b" + _OF + r"(\d{4})\b", folded)
        if m and _ORDINALS[m.group(1)] <= 2:
            half, year = _ORDINALS[m.group(1)], int(m.group(2))
            return _span(year, 1 + 6 * (half - 1), 6, f"{year}-H{half}")
        m = re.search(r"\b(\d{4})\s*-?\s*h([12])\b", folded) or re.search(r"\bh([12])\s*-?\s*(\d{4})\b", folded)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            year, half = (a, b) if a > 12 else (b, a)
            return _span(year, 1 + 6 * (half - 1), 6, f"{year}-H{half}")
        m = re.search(rf"\b({_ORDINAL_RE})\s+(?:trimestre|quarter)\b" + _OF + r"(\d{4})\b", folded)
        if m:
            quarter, year = _ORDINALS[m.group(1)], int(m.group(2))
            return _span(year, 1 + 3 * (quarter - 1), 3, f"{year}-Q{quarter}")
        m = re.search(r"\b(\d{4})\s*-?\s*q([1-4])\b", folded) or re.search(r"\bq([1-4])\s*-?\s*(\d{4})\b", folded)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            year, quarter = (a, b) if a > 4 else (b, a)
            return _span(year, 1 + 3 * (quarter - 1), 3, f"{year}-Q{quarter}")
        m = re.search(rf"\b({_MONTH_RE})\b" + _OF + r"(\d{4})\b", folded)
        if m:
            month, year = _MONTHS[m.group(1)], int(m.group(2))
            return _span(year, month, 1, f"{year}-{month:02d}")
        m = re.search(r"\b(\d{4})-(\d{1,2})\b", folded)
        if m and 1 <= int(m.group(2)) <= 12:
            year, month = int(m.group(1)), int(m.group(2))
            return _span(year, month, 1, f"{year}-{month:02d}")
        m = re.search(r"\b((?:19|20)\d{2})\b", folded)
        if m:
            year = int(m.group(1))
            return _span(year, 1, 12, str(year))
    except ValueError as e:
        raise KpiError(f"Invalid date in timeframe {raw!r}: {e}", error_type="invalid_timeframe") from e
    if strict:
        raise KpiError(
            f"Unrecognised timeframe {raw!r}; use YYYY-MM-DD..YYYY-MM-DD, YYYY, "
            "YYYY-H1, YYYY-Q2, YYYY-MM or 'primi N mesi del YYYY'",
            error_type="invalid_timeframe",
        )
    return None


# -- Question interpretation ----------------------------------------------------

_ENTITY_PATTERN = re.compile(
    r"\b(?:di|del|della|dello|dei|degli|delle|per|fornitore|supplier|vendor|for|of|from)\s+"
    r"(?P<name>[A-Z0-9][\w&.'\-]*(?:\s+[A-Z0-9][\w&.'\-]*)*)"
)
_ENTITY_PATTERN_LOWER = re.compile(
    r"\b(?:di|del|della|per|fornitore|supplier|of|for)\s+(?P<name>[a-z0-9][\w&.\-]*)"
    r"(?=\s+(?:nel|nei|nell|negli|in|per|dal|dall|tra|fra|during|from|between|over)\b|\s*[?.!,;]|\s*$)",
    re.IGNORECASE,
)
_NON_ENTITY_WORDS = frozenset(
    "mese mesi anno anni semestre trimestre primi ultimi month months year years quarter half "
    "ordinato lordo iva netto importo totale euro".split()
) | frozenset(_MONTHS)


def _is_time_like(name: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?|[HQhq][1-4]", name.strip()))


def extract_entity_name(question: str | None) -> str | None:
    """Best-effort entity extraction ('... di Novaconnect nel ...')."""

    if not question:
        return None
    for match in _ENTITY_PATTERN.finditer(question):
        name = match.group("name").strip(" .,;:?!'\"")
        if name and not _is_time_like(name) and name.upper() not in {"IVA"}:
            return name
    for match in _ENTITY_PATTERN_LOWER.finditer(question):
        name = match.group("name").strip(" .,;:?!'\"")
        if name and not _is_time_like(name) and _fold(name) not in _NON_ENTITY_WORDS and not name.isdigit():
            return name
    return None


def _is_metric_candidate(item: SourceField) -> bool:
    lowered = item.name.lower()
    return (
        item.base_type in NUMERIC_TYPES
        and not lowered.startswith("_")
        and not lowered.startswith("is_")
        and item.semantic_type not in {"type/PK", "type/FK", "type/Source"}
    )


def rank_metric_fields(text: str, fields: list[SourceField]) -> list[tuple[float, SourceField]]:
    """Rank numeric fields by how completely the text covers their name tokens."""

    query_tokens = set(_tokens(text))
    folded_query = _norm_name(text)
    ranked: list[tuple[float, SourceField]] = []
    for item in fields:
        if not _is_metric_candidate(item):
            continue
        name_tokens = _tokens(item.name)
        core = [t for t in name_tokens if t not in _CURRENCY]
        if not core:
            continue
        if _norm_name(item.name) == folded_query:
            score = 1.2
        else:
            hits = 0.0
            for token in core:
                if token in query_tokens:
                    hits += 1
                elif len(token) >= 4 and any(
                    len(q) >= 4 and (q.startswith(token) or token.startswith(q)) for q in query_tokens
                ):
                    hits += 0.8
            score = hits / len(core)
            if score and any(t in _CURRENCY for t in name_tokens):
                score += 0.05  # prefer EUR-normalised amounts
        if score > 0:
            ranked.append((round(score, 3), item))
    ranked.sort(key=lambda pair: (-pair[0], len(pair[1].name)))
    return ranked


# -- Entity field hints -----------------------------------------------------------

ENTITY_FIELD_HINTS: dict[str, tuple[tuple[str, float], ...]] = {
    "supplier": (
        ("fornitore", 1.0), ("nome fornitore", 1.0), ("ragione sociale", 0.95),
        ("ragione sociale fornitore", 0.95), ("supplier", 0.9), ("supplier name", 0.95),
        ("vendor", 0.85), ("conto fornitore", 0.6), ("codice fornitore", 0.6), ("supplier_key", 0.55),
    ),
    "company": (("descr societa", 1.0), ("societa", 0.8), ("company", 0.9)),
    "cost_center": (("descrizione centro di costo", 1.0), ("centro di costo", 0.8)),
    "wbs": (("descrizione elemento wbs", 1.0), ("elemento wbs", 0.8)),
    "material_group": (("definizione gr merci", 1.0), ("gr merci", 0.8)),
    "category": (("categoria procurement", 1.0), ("classificazione oda", 0.8)),
    "user": (("user creazione oda", 1.0), ("user rda", 0.8)),
}
_CODE_WORDS = frozenset({"conto", "codice", "key", "id", "code"})


def entity_name_score(item: SourceField, entity_type: str, *, numeric_entity: bool = False) -> float:
    if item.base_type not in TEXT_TYPES or item.name.startswith("_"):
        return 0.0
    if entity_type == "auto":
        hints = tuple(h for group in ENTITY_FIELD_HINTS.values() for h in group)
    else:
        hints = ENTITY_FIELD_HINTS[entity_type]
    name = _norm_name(item.name)
    name_words = set(name.split())
    exact = max((w for h, w in hints if _norm_name(h) == name), default=0.0)
    score = exact or max(
        (w * 0.7 for h, w in hints if set(_norm_name(h).split()) <= name_words), default=0.0
    )
    if score and numeric_entity:
        score = max(score, 0.95) if name_words & _CODE_WORDS else score * 0.6
    return round(score, 3)


# -- Query generation -------------------------------------------------------------


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _resolve_field(source: KpiSource, name: Any) -> SourceField:
    if not isinstance(name, str) or not name:
        raise KpiError("Field name must be a non-empty string", error_type="invalid_query")
    found = source.get_field(name)
    if found is None:
        suggestions = difflib.get_close_matches(name, [f.name for f in source.fields], n=3, cutoff=0.5)
        hint = f"; did you mean {suggestions}?" if suggestions else ""
        raise KpiError(f"Unknown field {name!r} in source {source.name!r}{hint}", error_type="unknown_field")
    return found


def _legacy_ref(source: KpiSource, item: SourceField, temporal_unit: str | None = None) -> list[Any]:
    if source.kind == "table" and item.id is not None:
        return ["field", item.id, {"temporal-unit": temporal_unit} if temporal_unit else None]
    opts: dict[str, Any] = {"base-type": item.base_type}
    if temporal_unit:
        opts["temporal-unit"] = temporal_unit
    return ["field", item.name, opts]


def _mbql5_ref(source: KpiSource, item: SourceField, temporal_unit: str | None = None) -> list[Any]:
    opts: dict[str, Any] = {"lib/uuid": _new_uuid(), "base-type": item.base_type, "effective-type": item.base_type}
    if temporal_unit:
        opts["temporal-unit"] = temporal_unit
    return ["field", opts, item.id if source.kind == "table" and item.id is not None else item.name]


def _coerce_value(item: SourceField, value: Any, op: str) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        raise KpiError(f"Filter value for {item.name!r} must be a scalar", error_type="invalid_query")
    if item.base_type in TEMPORAL_TYPES and op not in STRING_OPS:
        text = value.isoformat() if isinstance(value, date) else str(value)
        if not (_ISO_DATE.match(text) or _ISO_DATETIME.match(text)):
            raise KpiError(
                f"Temporal literal {value!r} for {item.name!r} must be YYYY-MM-DD or ISO datetime",
                error_type="invalid_query",
            )
        return text
    if item.base_type in NUMERIC_TYPES and op not in STRING_OPS:
        if isinstance(value, bool):
            raise KpiError(f"Boolean is not a valid value for numeric {item.name!r}", error_type="invalid_query")
        try:
            number = float(value)
        except (TypeError, ValueError) as e:
            raise KpiError(f"Value {value!r} is not numeric for {item.name!r}", error_type="invalid_query") from e
        return int(number) if number.is_integer() and item.base_type != "type/Float" else number
    return str(value)


def _build_filter(source: KpiSource, node: dict[str, Any], legacy: bool) -> list[Any]:
    if not isinstance(node, dict):
        raise KpiError("Filter nodes must be objects", error_type="invalid_query")
    for logical in ("and", "or"):
        if logical in node:
            children = [_build_filter(source, child, legacy) for child in node[logical] or []]
            if not children:
                raise KpiError(f"'{logical}' filter needs at least one child", error_type="invalid_query")
            if len(children) == 1:
                return children[0]
            return [logical, *children] if legacy else [logical, {"lib/uuid": _new_uuid()}, *children]
    if "not" in node:
        child = _build_filter(source, node["not"], legacy)
        return ["not", child] if legacy else ["not", {"lib/uuid": _new_uuid()}, child]

    op = node.get("op", "=")
    if op not in FILTER_ARITY:
        raise KpiError(f"Unsupported filter operator {op!r}", error_type="invalid_query")
    item = _resolve_field(source, node.get("field"))
    values = node.get("values")
    if values is None and "value" in node:
        values = [node["value"]]
    values = list(values or [])
    low, high = FILTER_ARITY[op]
    if len(values) < low or (high is not None and len(values) > high):
        raise KpiError(f"Operator {op!r} on {item.name!r} expects {low}..{high or 'n'} values", error_type="invalid_query")
    if op in STRING_OPS and item.base_type not in TEXT_TYPES:
        raise KpiError(f"String operator {op!r} needs a text field, {item.name!r} is {item.base_type}", error_type="invalid_query")
    coerced = [_coerce_value(item, value, op) for value in values]
    if op == "between" and coerced[0] > coerced[1]:
        raise KpiError(f"'between' bounds for {item.name!r} are reversed", error_type="invalid_query")
    case_sensitive = bool(node.get("case_sensitive", False))
    if legacy:
        clause: list[Any] = [op, _legacy_ref(source, item), *coerced]
        if op in STRING_OPS:
            clause.append({"case-sensitive": case_sensitive})
        return clause
    opts: dict[str, Any] = {"lib/uuid": _new_uuid()}
    if op in STRING_OPS:
        opts["case-sensitive"] = case_sensitive
    return [op, opts, _mbql5_ref(source, item), *coerced]


def build_queries(source: KpiSource, spec: dict[str, Any]) -> dict[str, Any]:
    """Generate REST-executable legacy MBQL, MBQL 5 and portable MBQL 5 queries.

    spec keys: aggregation [{op, field}], filters (tree of {field, op, values}
    and {and|or|not: ...}), breakout [{field, temporal_unit}], order_by
    [{aggregation: index | field, temporal_unit, direction}], limit.
    """

    legacy: dict[str, Any] = {}
    stage: dict[str, Any] = {"lib/type": "mbql.stage/mbql"}
    if source.kind == "card":
        legacy["source-table"] = f"card__{source.id}"
        stage["source-card"] = source.id
    else:
        legacy["source-table"] = source.id
        stage["source-table"] = source.id

    agg_uuids: list[str] = []
    legacy_aggs: list[Any] = []
    mbql5_aggs: list[Any] = []
    for agg in spec.get("aggregation") or []:
        op = agg.get("op", "sum")
        if op not in AGGREGATIONS:
            raise KpiError(f"Unsupported aggregation {op!r}", error_type="invalid_query")
        agg_uuid = _new_uuid()
        agg_uuids.append(agg_uuid)
        if not agg.get("field"):
            if AGGREGATIONS[op]:
                raise KpiError(f"Aggregation {op!r} requires a field", error_type="invalid_query")
            legacy_aggs.append([op])
            mbql5_aggs.append([op, {"lib/uuid": agg_uuid}])
            continue
        item = _resolve_field(source, agg["field"])
        if op in {"sum", "avg"} and item.base_type not in NUMERIC_TYPES:
            raise KpiError(f"Aggregation {op!r} needs a numeric field, {item.name!r} is {item.base_type}", error_type="invalid_query")
        legacy_aggs.append([op, _legacy_ref(source, item)])
        mbql5_aggs.append([op, {"lib/uuid": agg_uuid}, _mbql5_ref(source, item)])
    if legacy_aggs:
        legacy["aggregation"] = legacy_aggs
        stage["aggregation"] = mbql5_aggs

    legacy_breakouts: list[Any] = []
    mbql5_breakouts: list[Any] = []
    for brk in spec.get("breakout") or []:
        item = _resolve_field(source, brk.get("field"))
        unit = brk.get("temporal_unit")
        if unit is not None:
            if unit not in TEMPORAL_UNITS:
                raise KpiError(f"temporal_unit must be one of {TEMPORAL_UNITS}", error_type="invalid_query")
            if item.base_type not in TEMPORAL_TYPES:
                raise KpiError(f"temporal_unit needs a temporal field, {item.name!r} is {item.base_type}", error_type="invalid_query")
        legacy_breakouts.append(_legacy_ref(source, item, unit))
        mbql5_breakouts.append(_mbql5_ref(source, item, unit))
    if legacy_breakouts:
        legacy["breakout"] = legacy_breakouts
        stage["breakout"] = mbql5_breakouts

    filters = spec.get("filters")
    if filters:
        legacy["filter"] = _build_filter(source, filters, legacy=True)
        top = _build_filter(source, filters, legacy=False)
        stage["filters"] = top[2:] if top[0] == "and" else [top]

    legacy_order: list[Any] = []
    mbql5_order: list[Any] = []
    for order in spec.get("order_by") or []:
        direction = order.get("direction", "asc")
        if direction not in {"asc", "desc"}:
            raise KpiError("order direction must be 'asc' or 'desc'", error_type="invalid_query")
        if "aggregation" in order:
            index = order["aggregation"]
            if not isinstance(index, int) or not 0 <= index < len(agg_uuids):
                raise KpiError(f"order_by aggregation index {index!r} is out of range", error_type="invalid_query")
            legacy_order.append([direction, ["aggregation", index]])
            mbql5_order.append(
                [direction, {"lib/uuid": _new_uuid()}, ["aggregation", {"lib/uuid": _new_uuid()}, agg_uuids[index]]]
            )
        else:
            item = _resolve_field(source, order.get("field"))
            unit = order.get("temporal_unit")
            legacy_order.append([direction, _legacy_ref(source, item, unit)])
            mbql5_order.append([direction, {"lib/uuid": _new_uuid()}, _mbql5_ref(source, item, unit)])
    if legacy_order:
        legacy["order-by"] = legacy_order
        stage["order-by"] = mbql5_order

    limit = spec.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or limit <= 0:
            raise KpiError("limit must be a positive integer", error_type="invalid_query")
        legacy["limit"] = limit
        stage["limit"] = limit

    mbql5 = {"database": source.database_id, "lib/type": "mbql/query", "stages": [stage]}
    portable = None
    if source.kind == "card" and source.entity_id and source.database_name:
        portable = copy.deepcopy(mbql5)
        portable["database"] = source.database_name
        portable["stages"][0]["source-card"] = source.entity_id
    return {
        "legacy": {"database": source.database_id, "type": "query", "query": legacy},
        "mbql5": mbql5,
        "mbql5_portable": portable,
    }


# -- Query validation -------------------------------------------------------------


class _Validator:
    def __init__(self, source: KpiSource | None):
        self.source = source
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.uuids: set[str] = set()

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def field_type(self, path: str, key: Any, opts: Any) -> str | None:
        base_type = opts.get("base-type") if isinstance(opts, dict) else None
        if isinstance(key, str):
            if not base_type:
                self.error(path, f"name-based field ref {key!r} needs a 'base-type' option")
            if self.source is not None and self.source.kind == "card":
                known = self.source.get_field(key)
                if known is None:
                    suggestions = difflib.get_close_matches(key, [f.name for f in self.source.fields], n=3, cutoff=0.5)
                    self.error(path, f"unknown field {key!r}" + (f" (did you mean {suggestions}?)" if suggestions else ""))
                elif not base_type:
                    base_type = known.base_type
        elif isinstance(key, int):
            if self.source is not None and self.source.kind == "table":
                known = next((f for f in self.source.fields if f.id == key), None)
                if known is None:
                    self.error(path, f"unknown field id {key}")
                elif not base_type:
                    base_type = known.base_type
        else:
            self.error(path, "field ref must use a field name or integer id")
        if isinstance(opts, dict):
            unit = opts.get("temporal-unit")
            if unit is not None:
                if unit not in TEMPORAL_UNITS:
                    self.error(path, f"invalid temporal-unit {unit!r}")
                elif base_type and base_type not in TEMPORAL_TYPES:
                    self.error(path, f"temporal-unit on non-temporal field ({base_type})")
        return base_type

    def ref(self, path: str, ref: Any, mbql5: bool) -> str | None:
        if not isinstance(ref, list) or len(ref) != 3 or ref[0] != "field":
            self.error(path, f"expected a field ref, got {json.dumps(ref, default=str)[:120]}")
            return None
        if mbql5:
            opts, key = ref[1], ref[2]
            if not isinstance(opts, dict):
                self.error(path, "MBQL 5 field ref options must be an object")
                return None
            self.uuid(path, opts)
        else:
            key, opts = ref[1], ref[2]
            if opts is not None and not isinstance(opts, dict):
                self.error(path, "field ref options must be an object or null")
        return self.field_type(path, key, opts)

    def uuid(self, path: str, opts: Any) -> None:
        value = opts.get("lib/uuid") if isinstance(opts, dict) else None
        if not isinstance(value, str) or not value:
            self.error(path, "MBQL 5 clause options need a 'lib/uuid'")
        elif value in self.uuids:
            self.error(path, f"duplicate lib/uuid {value}")
        else:
            self.uuids.add(value)

    def literal(self, path: str, value: Any, base_type: str | None, op: str) -> None:
        if isinstance(value, (dict, list)):
            self.error(path, "filter values must be literals")
        elif base_type in TEMPORAL_TYPES and op not in STRING_OPS:
            if not isinstance(value, str) or not (_ISO_DATE.match(value) or _ISO_DATETIME.match(value)):
                self.error(path, f"temporal literal {value!r} must be YYYY-MM-DD or ISO datetime")
        elif base_type in NUMERIC_TYPES and op not in STRING_OPS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self.error(path, f"numeric field needs a number, got {value!r}")
        elif op in STRING_OPS and not isinstance(value, str):
            self.error(path, f"{op!r} needs a string value")

    def filter(self, path: str, clause: Any, mbql5: bool) -> None:
        if not isinstance(clause, list) or not clause or not isinstance(clause[0], str):
            self.error(path, "filter clause must be a list starting with an operator")
            return
        op = clause[0]
        rest = clause[1:]
        if mbql5:
            if not rest:
                self.error(path, "missing clause options")
                return
            self.uuid(path, rest[0])
            rest = rest[1:]
        if op in LOGICAL_OPS:
            if op == "not" and len(rest) != 1:
                self.error(path, "'not' takes exactly one clause")
            elif op != "not" and len(rest) < 2:
                self.warnings.append(f"{path}: '{op}' with fewer than two clauses")
            for index, child in enumerate(rest):
                self.filter(f"{path}.{op}[{index}]", child, mbql5)
            return
        if op not in FILTER_ARITY:
            self.error(path, f"unsupported filter operator {op!r}")
            return
        if not rest:
            self.error(path, f"{op!r} needs a field ref")
            return
        base_type = self.ref(f"{path}.field", rest[0], mbql5)
        values = rest[1:]
        if not mbql5 and op in STRING_OPS and values and isinstance(values[-1], dict):
            values = values[:-1]
        low, high = FILTER_ARITY[op]
        if len(values) < low or (high is not None and len(values) > high):
            self.error(path, f"{op!r} expects {low}..{high or 'n'} values, got {len(values)}")
        for index, value in enumerate(values):
            self.literal(f"{path}.values[{index}]", value, base_type, op)
        if op == "between" and len(values) == 2 and all(isinstance(v, (str, int, float)) for v in values):
            if type(values[0]) is type(values[1]) and values[0] > values[1]:
                self.error(path, "'between' bounds are reversed")

    def aggregation(self, path: str, clause: Any, mbql5: bool) -> None:
        if not isinstance(clause, list) or not clause:
            self.error(path, "aggregation must be a non-empty list")
            return
        op = clause[0]
        rest = clause[1:]
        if mbql5:
            if not rest:
                self.error(path, "missing clause options")
                return
            self.uuid(path, rest[0])
            rest = rest[1:]
        if op not in AGGREGATIONS:
            self.warnings.append(f"{path}: aggregation {op!r} is not checked by the validator")
            return
        if AGGREGATIONS[op] and len(rest) != 1:
            self.error(path, f"{op!r} needs exactly one field ref")
        elif not AGGREGATIONS[op] and len(rest) > 1:
            self.error(path, f"{op!r} takes at most one field ref")
        for ref in rest:
            base_type = self.ref(f"{path}.field", ref, mbql5)
            if op in {"sum", "avg"} and base_type and base_type not in NUMERIC_TYPES:
                self.error(path, f"{op!r} on non-numeric field ({base_type})")

    def order(self, path: str, clause: Any, mbql5: bool, aggregation_count: int) -> None:
        if not isinstance(clause, list) or len(clause) != (3 if mbql5 else 2) or clause[0] not in {"asc", "desc"}:
            self.error(path, "order-by must be [asc|desc, ref]")
            return
        if mbql5:
            self.uuid(path, clause[1])
        target = clause[-1]
        if isinstance(target, list) and target and target[0] == "aggregation":
            if not mbql5 and not (len(target) == 2 and isinstance(target[1], int) and 0 <= target[1] < aggregation_count):
                self.error(path, "aggregation reference index out of range")
        else:
            self.ref(path, target, mbql5)


def validate_query(query: Any, source: KpiSource | None = None) -> dict[str, Any]:
    """Structurally validate legacy MBQL or MBQL 5 without executing it."""

    v = _Validator(source)
    fmt = "unknown"
    if not isinstance(query, dict):
        v.error("query", "must be an object")
    elif "stages" in query:
        fmt = "mbql5"
        if query.get("lib/type") != "mbql/query":
            v.error("lib/type", "must be 'mbql/query'")
        database = query.get("database")
        if isinstance(database, str):
            fmt = "mbql5_portable"
            v.warnings.append("database is a name: portable form for construct_query, not REST execution")
        elif not isinstance(database, int):
            v.error("database", "must be an integer id (or a database name for portable queries)")
        stages = query.get("stages")
        if not isinstance(stages, list) or not stages:
            v.error("stages", "must be a non-empty list")
            stages = []
        for index, stage in enumerate(stages):
            path = f"stages[{index}]"
            if not isinstance(stage, dict):
                v.error(path, "must be an object")
                continue
            if stage.get("lib/type") not in {"mbql.stage/mbql", "mbql.stage/native"}:
                v.error(f"{path}.lib/type", "must be 'mbql.stage/mbql' or 'mbql.stage/native'")
            if stage.get("lib/type") == "mbql.stage/native":
                if not isinstance(stage.get("native"), str):
                    v.error(f"{path}.native", "must be SQL text")
                continue
            if index == 0:
                sources = [key for key in ("source-card", "source-table") if key in stage]
                if len(sources) != 1:
                    v.error(path, "first stage needs exactly one of source-card or source-table")
                elif not isinstance(stage[sources[0]], (int, str, list)):
                    v.error(f"{path}.{sources[0]}", "must be an id, entity id or portable table path")
            aggregations = stage.get("aggregation") or []
            for i, clause in enumerate(aggregations):
                v.aggregation(f"{path}.aggregation[{i}]", clause, True)
            for i, ref in enumerate(stage.get("breakout") or []):
                v.ref(f"{path}.breakout[{i}]", ref, True)
            filters = stage.get("filters") or []
            if not isinstance(filters, list):
                v.error(f"{path}.filters", "must be a list of clauses")
                filters = []
            for i, clause in enumerate(filters):
                v.filter(f"{path}.filters[{i}]", clause, True)
            for i, clause in enumerate(stage.get("order-by") or []):
                v.order(f"{path}.order-by[{i}]", clause, True, len(aggregations))
            if "limit" in stage and (not isinstance(stage["limit"], int) or stage["limit"] <= 0):
                v.error(f"{path}.limit", "must be a positive integer")
    elif query.get("type") == "query":
        fmt = "legacy"
        if not isinstance(query.get("database"), int):
            v.error("database", "must be an integer id")
        inner = query.get("query")
        if not isinstance(inner, dict):
            v.error("query", "must be an object")
            inner = {}
        sources = [key for key in ("source-table", "source-query") if key in inner]
        if len(sources) != 1:
            v.error("query", "needs exactly one of source-table or source-query")
        elif sources[0] == "source-table":
            table = inner["source-table"]
            if not (isinstance(table, int) or (isinstance(table, str) and _CARD_SOURCE.match(table))):
                v.error("query.source-table", "must be a table id or 'card__<id>'")
        aggregations = inner.get("aggregation") or []
        for i, clause in enumerate(aggregations):
            v.aggregation(f"query.aggregation[{i}]", clause, False)
        for i, ref in enumerate(inner.get("breakout") or []):
            v.ref(f"query.breakout[{i}]", ref, False)
        if inner.get("filter") is not None:
            v.filter("query.filter", inner["filter"], False)
        for i, clause in enumerate(inner.get("order-by") or []):
            v.order(f"query.order-by[{i}]", clause, False, len(aggregations))
        if "limit" in inner and (not isinstance(inner["limit"], int) or inner["limit"] <= 0):
            v.error("query.limit", "must be a positive integer")
    elif query.get("type") == "native":
        fmt = "native"
        native = query.get("native")
        if not isinstance(native, dict) or not isinstance(native.get("query"), str):
            v.error("native.query", "must be SQL text")
        v.warnings.append("native query: only structural checks are applied")
    else:
        v.error("query", "unknown format: expected legacy MBQL (type=query), native, or MBQL 5 (stages)")
    return {"valid": not v.errors, "format": fmt, "errors": v.errors, "warnings": v.warnings}


# -- Native SQL fallback ----------------------------------------------------------


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_literal(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


_SQL_AGGREGATIONS = {"sum": "SUM({})", "avg": "AVG({})", "min": "MIN({})", "max": "MAX({})", "distinct": "COUNT(DISTINCT {})"}
_SQL_OPS = {"=": "=", "!=": "<>", "<": "<", ">": ">", "<=": "<=", ">=": ">="}


def build_native_query(
    source: KpiSource,
    *,
    aggregation: str,
    metric: SourceField | None,
    filters: list[dict[str, Any]],
    breakout_field: SourceField | None,
    breakout_unit: str | None,
) -> dict[str, Any] | None:
    """Parameterised PostgreSQL over the source model via a {{#card}} reference."""

    if source.kind != "card":
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(source.name)).strip("-") or "source"
    card_tag = f"#{source.id}-{slug}"
    tags: dict[str, Any] = {
        card_tag: {"id": _new_uuid(), "name": card_tag, "display-name": card_tag, "type": "card", "card-id": source.id}
    }
    parameters: list[dict[str, Any]] = []
    preview_values: dict[str, Any] = {}

    def variable(value: Any, item: SourceField) -> str:
        name = f"p{len(parameters) + 1}"
        if item.base_type in TEMPORAL_TYPES:
            tag_type, param_type = "date", "date/single"
        elif item.base_type in NUMERIC_TYPES and isinstance(value, (int, float)):
            tag_type, param_type = "number", "number/="
        else:
            tag_type, param_type = "text", "category"
        tags[name] = {"id": _new_uuid(), "name": name, "display-name": name, "type": tag_type}
        parameters.append({"type": param_type, "target": ["variable", ["template-tag", name]], "value": value})
        preview_values[name] = value
        return "{{" + name + "}}"

    conditions: list[str] = []
    for node in filters:
        item = _resolve_field(source, node["field"])
        column = f"src.{_quote_ident(item.name)}"
        op = node.get("op", "=")
        values = [_coerce_value(item, value, op) for value in node.get("values") or []]
        if op == "between":
            conditions.append(f"{column} BETWEEN {variable(values[0], item)} AND {variable(values[1], item)}")
        elif op in STRING_OPS:
            pattern = {"contains": "'%' || {} || '%'", "does-not-contain": "'%' || {} || '%'",
                       "starts-with": "{} || '%'", "ends-with": "'%' || {}"}[op].format(variable(values[0], item))
            keyword = "NOT ILIKE" if op == "does-not-contain" else "ILIKE"
            if node.get("case_sensitive"):
                keyword = keyword.replace("ILIKE", "LIKE")
            conditions.append(f"{column} {keyword} {pattern}")
        elif op in {"=", "!="} and len(values) > 1:
            placeholders = ", ".join(variable(value, item) for value in values)
            conditions.append(f"{column} {'IN' if op == '=' else 'NOT IN'} ({placeholders})")
        elif op in _SQL_OPS:
            conditions.append(f"{column} {_SQL_OPS[op]} {variable(values[0], item)}")
        elif op == "is-null":
            conditions.append(f"{column} IS NULL")
        elif op == "not-null":
            conditions.append(f"{column} IS NOT NULL")
        else:
            return None

    if aggregation == "count" and metric is None:
        value_expr = "COUNT(*)"
    elif metric is not None and aggregation in _SQL_AGGREGATIONS:
        value_expr = _SQL_AGGREGATIONS[aggregation].format(f"src.{_quote_ident(metric.name)}")
    else:
        return None
    select = [f"{value_expr} AS value"]
    group = ""
    if breakout_field is not None:
        column = f"src.{_quote_ident(breakout_field.name)}"
        period = f"date_trunc('{breakout_unit}', {column})" if breakout_unit else column
        select.insert(0, f"{period} AS period")
        group = "\nGROUP BY 1\nORDER BY 1"
    where = ("\nWHERE " + "\n  AND ".join(conditions)) if conditions else ""
    sql = f"SELECT {', '.join(select)}\nFROM {{{{{card_tag}}}}} AS src{where}{group}"
    preview = sql
    for name, value in preview_values.items():
        preview = preview.replace("{{" + name + "}}", _sql_literal(value))
    preview = preview.replace("{{" + card_tag + "}}", f"({source.name} model, card {source.id})")
    return {
        "query": {
            "database": source.database_id,
            "type": "native",
            "native": {"query": sql, "template-tags": tags},
            "parameters": parameters,
        },
        "sql_preview": preview,
    }


# -- Saved-question parameters --------------------------------------------------

PARAMETER_FORMATS = {
    "date/single": "YYYY-MM-DD",
    "date/range": "YYYY-MM-DD~YYYY-MM-DD",
    "date/month-year": "YYYY-MM",
    "date/quarter-year": "Q1-YYYY",
    "date/relative": "past30days | thisyear | ...",
    "date/all-options": "YYYY-MM-DD~YYYY-MM-DD | past3months | thisyear",
    "number/=": "number or list of numbers",
    "number/!=": "number or list of numbers",
    "number/between": "[min, max]",
    "string/=": "string or list of strings",
    "string/!=": "string or list of strings",
    "string/contains": "string",
    "string/starts-with": "string",
    "category": "string or list of strings",
    "id": "id or list of ids",
    "temporal-unit": "day | week | month | quarter | year",
}
_TAG_PARAMETER_TYPES = {"text": "category", "number": "number/=", "date": "date/single", "temporal-unit": "temporal-unit"}


def _target_tag(target: Any) -> str | None:
    if isinstance(target, list) and len(target) >= 2:
        inner = target[1]
        if isinstance(inner, list) and len(inner) >= 2 and inner[0] == "template-tag":
            return inner[1]
    return None


def _describe_parameter(param: dict[str, Any], tag: dict[str, Any] | None) -> dict[str, Any]:
    ptype = param.get("type")
    config = param.get("values_source_config") or {}
    allowed = config.get("values") if param.get("values_source_type") == "static-list" else None
    return {
        "id": param.get("id"),
        "name": param.get("name"),
        "slug": param.get("slug"),
        "type": ptype,
        "widget_type": (tag or {}).get("widget-type") or ptype,
        "tag_type": (tag or {}).get("type"),
        "required": bool(param.get("required") or (tag or {}).get("required")),
        "default": param.get("default", (tag or {}).get("default")),
        "target": param.get("target"),
        "values_source": param.get("values_source_type") or "default",
        "allowed_values": allowed[:50] if isinstance(allowed, list) else None,
        "format": PARAMETER_FORMATS.get(str(ptype), "string"),
    }


def build_card_parameter_payload(
    parameters: list[dict[str, Any]], values: dict[str, Any]
) -> list[dict[str, Any]]:
    """Map {slug|name|id: value} onto exact Metabase parameter bindings."""

    index: dict[str, dict[str, Any]] = {}
    for param in parameters:
        for key in (param.get("id"), param.get("slug"), param.get("name")):
            if key:
                index.setdefault(_fold(key), param)
    payload: list[dict[str, Any]] = []
    for key, value in values.items():
        param = index.get(_fold(key))
        if param is None:
            available = [f"{p.get('slug') or p.get('name')} ({p.get('type')})" for p in parameters]
            raise KpiError(f"Unknown parameter {key!r}; available: {available}", error_type="unknown_parameter")
        ptype = str(param.get("type") or "")
        if not ptype.startswith("date/") and ptype != "temporal-unit" and not isinstance(value, list):
            value = [value]
        payload.append({"id": param["id"], "type": ptype, "target": param["target"], "value": value})
    supplied = {item["id"] for item in payload}
    missing = [
        p.get("slug") or p.get("name")
        for p in parameters
        if p.get("required") and p.get("default") is None and p.get("id") not in supplied
    ]
    if missing:
        raise KpiError(f"Missing required parameters: {missing}", error_type="missing_parameter")
    return payload


# -- Result helpers ---------------------------------------------------------------


def _parse_dataset(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise KpiError("Unexpected query response", error_type="invalid_response")
    if response.get("status") == "failed" or (response.get("error") and not (response.get("data") or {}).get("rows")):
        raise KpiError(str(response.get("error") or "query failed")[:500], error_type=response.get("error_type") or "query_failed")
    data = response.get("data") or {}
    cols = [c.get("display_name") or c.get("name") for c in data.get("cols") or []]
    return {"columns": cols, "rows": data.get("rows") or [], "row_count": response.get("row_count", len(data.get("rows") or []))}


def _error_from_client(exc: MetabaseClientError) -> KpiError:
    text = str(exc)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        message = payload.get("error") or payload.get("message") or text
        return KpiError(str(message)[:500], error_type=payload.get("error_type") or f"http_{exc.status_code}")
    return KpiError(text[:500], error_type=f"http_{exc.status_code}" if exc.status_code else "request_failed")


def _period_label(value: Any, unit: str | None) -> str:
    text = str(value)
    if not re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text
    year, month = text[:4], int(text[5:7])
    if unit == "month":
        return f"{year}-{month:02d}"
    if unit == "quarter":
        return f"{year}-Q{(month - 1) // 3 + 1}"
    if unit == "year":
        return year
    return text[:10]


def format_amount(value: float | None, currency: str | None) -> str | None:
    if value is None:
        return None
    text = f"{value:,.2f}".replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")
    return f"€ {text}" if currency == "EUR" else text


def _describe_filter(node: dict[str, Any]) -> str:
    op = node.get("op", "=")
    values = node.get("values") or []
    if op == "between":
        return f"{node['field']} between {values[0]} and {values[1]}"
    if op in STRING_OPS:
        suffix = "" if node.get("case_sensitive") else " (case-insensitive)"
        return f"{node['field']} {op} {values[0]!r}{suffix}"
    if op in {"is-null", "not-null"}:
        return f"{node['field']} {op}"
    return f"{node['field']} {op} " + " OR ".join(repr(v) for v in values)


# -- Assistant --------------------------------------------------------------------


class AnalyticsAssistant:
    """KPI orchestration over the Ditra Analytics REST API."""

    def __init__(
        self,
        client: MetabaseClient,
        *,
        canonical_card_id: int = 685,
        date_field: str | None = None,
        cache_ttl_seconds: float = 600.0,
    ):
        self._client = client
        self._canonical_card_id = canonical_card_id
        self._date_field = date_field
        self._ttl = cache_ttl_seconds
        self._sources: dict[tuple[str, int], tuple[float, KpiSource]] = {}
        self._databases: dict[int, tuple[float, dict[str, Any]]] = {}
        self._native: dict[int, tuple[float, dict[str, Any]]] = {}

    @property
    def canonical_card_id(self) -> int:
        return self._canonical_card_id

    async def answer_dashboard_kpi(
        self,
        kpi_name: str,
        *,
        timeframe: str | None = None,
        source: str | None = None,
        dashboard_id: int | None = None,
        tab_name: str = "KPI",
        card_id: int | None = None,
        period_parameter: str = "date_range",
    ) -> dict[str, Any]:
        """Run a saved KPI in its dashboard context using the placement's filter binding."""
        if not kpi_name.strip() and card_id is None:
            return {"status": "invalid_input", "reason": "Provide a KPI name or card_id."}
        if not timeframe:
            return {"status": "invalid_input", "reason": "Provide a period; the dashboard's active browser filter is not visible to the MCP."}
        try:
            period = parse_timeframe(timeframe)
        except KpiError as exc:
            return {"status": "invalid_input", "reason": str(exc)}
        target_id = dashboard_id or self._client.settings.default_dashboard_id
        try:
            dashboard = (await self._client.get_dashboard(target_id)).data
        except MetabaseClientError as exc:
            raise _error_from_client(exc) from exc
        tabs = dashboard.get("tabs") or []
        tab = next((item for item in tabs if _norm_name(item.get("name")) == _norm_name(tab_name)), None)
        if tab is None:
            return {"status": "not_found", "reason": f"Dashboard {target_id} has no tab {tab_name!r}."}
        placements = [
            item for item in dashboard.get("dashcards") or []
            if item.get("dashboard_tab_id") == tab["id"] and (item.get("card") or {}).get("id")
        ]
        if card_id is not None:
            candidates = [item for item in placements if item["card"]["id"] == card_id]
        else:
            name = _norm_name(kpi_name)
            candidates = [
                item for item in placements
                if _norm_name((item["card"].get("name") or "").split("|", 1)[-1].split(" - ", 1)[0]) == name
            ]
            if not candidates:
                candidates = [
                    item for item in placements
                    if similarity(name, (item["card"].get("name") or "").split("|", 1)[-1].split(" - ", 1)[0]) >= 0.85
                ]
        if source:
            candidates = [item for item in candidates if _norm_name(source) in _norm_name(item["card"].get("name"))]
        choices = [{"card_id": item["card"]["id"], "dashcard_id": item["id"],
                    "name": item["card"].get("name")} for item in candidates]
        if len(candidates) != 1:
            return {"status": "ambiguous" if candidates else "not_found",
                    "reason": "Specify a source or card_id to select exactly one KPI placement." if candidates
                    else "No matching saved KPI on the dashboard tab.", "candidates": choices}
        placement = candidates[0]
        parameter = next(
            (item for item in dashboard.get("parameters") or []
             if _norm_name(item.get("slug")) == _norm_name(period_parameter)), None
        )
        if parameter is None or parameter.get("type") != "date/range":
            return {"status": "blocked", "reason": f"Dashboard period parameter {period_parameter!r} is missing or not a date/range."}
        mappings = [
            item for item in placement.get("parameter_mappings") or []
            if item.get("parameter_id") == parameter["id"] and item.get("card_id") == placement["card"]["id"]
            and item.get("target")
        ]
        if len(mappings) != 1:
            return {"status": "blocked", "reason": "The selected card has no unique mapping for the dashboard period filter.",
                    "card": choices[0]}
        applied = {"id": parameter["id"], "type": parameter["type"],
                   "target": mappings[0]["target"],
                   "value": f"{period.start.isoformat()}~{period.end.isoformat()}"}
        try:
            response = (await self._client.get_dashboard_card_data(
                target_id, placement["card"]["id"], placement["id"], parameters=[applied]
            )).data
            data = _parse_dataset(response)
        except MetabaseClientError as exc:
            raise _error_from_client(exc) from exc
        answer = {"columns": data["columns"], "rows": data["rows"][:100], "row_count": data["row_count"]}
        if len(data["rows"]) == 1 and len(data["rows"][0]) == 1:
            answer["value"] = data["rows"][0][0]
        return {"status": "ok", "strategy": "dashboard_card", "answer": answer,
                "dashboard_id": target_id, "tab": tab_name, "card": choices[0],
                "period": period.as_dict(), "parameter_applied": applied}

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return await self._client._request(method, path, **kwargs)
        except MetabaseClientError as e:
            raise _error_from_client(e) from e

    async def run_dataset(self, query: dict[str, Any]) -> dict[str, Any]:
        return _parse_dataset(await self._call("POST", "/api/dataset", json=query))

    async def _database(self, database_id: int) -> dict[str, Any]:
        cached = self._databases.get(database_id)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        data = await self._call("GET", f"/api/database/{database_id}")
        info = {
            "id": data.get("id", database_id),
            "name": data.get("name"),
            "engine": data.get("engine"),
            "native_permissions": data.get("native_permissions"),
        }
        self._databases[database_id] = (time.monotonic(), info)
        return info

    # -- Sources --------------------------------------------------------------

    async def load_source(self, source_id: int | None = None, kind: str = "card") -> KpiSource:
        if kind not in {"card", "table"}:
            raise KpiError("source kind must be 'card' or 'table'", error_type="invalid_input")
        source_id = source_id or self._canonical_card_id
        key = (kind, source_id)
        cached = self._sources.get(key)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        if kind == "card":
            card = await self._call("GET", f"/api/card/{source_id}")
            metadata = card.get("result_metadata") or []
            fields = [
                SourceField(
                    name=c["name"],
                    base_type=c.get("base_type") or c.get("effective_type") or "type/*",
                    display_name=c.get("display_name"),
                    semantic_type=c.get("semantic_type"),
                )
                for c in metadata
                if c.get("name")
            ]
            name, database_id = card.get("name") or f"card {source_id}", card.get("database_id")
            entity_id, source_type = card.get("entity_id"), card.get("type")
        else:
            table = await self._call("GET", f"/api/table/{source_id}/query_metadata")
            fields = [
                SourceField(
                    name=f["name"],
                    base_type=f.get("base_type") or "type/*",
                    display_name=f.get("display_name"),
                    semantic_type=f.get("semantic_type"),
                    id=f.get("id"),
                )
                for f in table.get("fields") or []
                if f.get("name")
            ]
            name, database_id = table.get("name") or f"table {source_id}", table.get("db_id")
            entity_id, source_type = None, "table"
        if not fields:
            raise KpiError(f"Source {kind} {source_id} exposes no column metadata", error_type="no_metadata")
        if not isinstance(database_id, int):
            raise KpiError(f"Source {kind} {source_id} has no database id", error_type="no_metadata")
        try:
            database_name = (await self._database(database_id)).get("name")
        except KpiError:
            database_name = None
        known = next((s for s in KNOWN_SOURCES if s["kind"] == kind and s["id"] == source_id), {})
        source = KpiSource(
            kind=kind,
            id=source_id,
            name=name,
            database_id=database_id,
            database_name=database_name,
            entity_id=entity_id,
            source_type=source_type,
            fields=fields,
            role=known.get("role", "candidate"),
            date_field=known.get("date_field"),
            default_filters=copy.deepcopy(known.get("default_filters", [])),
            notes=known.get("notes"),
        )
        if kind == "card" and source_id == self._canonical_card_id:
            source.role = "canonical"
            if self._date_field:
                source.date_field = self._date_field
        elif source.role == "canonical":
            source.role = "alternative"
        self._sources[key] = (time.monotonic(), source)
        return source

    def resolve_date_field(self, source: KpiSource, requested: str | None = None) -> SourceField | None:
        if requested:
            item = _resolve_field(source, requested)
            if item.base_type not in TEMPORAL_TYPES:
                raise KpiError(f"Date field {item.name!r} is {item.base_type}, not temporal", error_type="invalid_input")
            return item
        if source.date_field:
            item = source.get_field(source.date_field)
            if item is not None and item.base_type in TEMPORAL_TYPES:
                return item
        temporal = [f for f in source.fields if f.base_type in TEMPORAL_TYPES and not f.name.startswith("_")]
        for preferred in ("oda_date", "data_doc", "date"):
            for item in temporal:
                if preferred in item.name.lower():
                    return item
        return temporal[0] if temporal else None

    async def describe_source(
        self, source_id: int | None = None, kind: str = "card", expand: bool = False
    ) -> dict[str, Any]:
        source = await self.load_source(source_id, kind)
        date_field = self.resolve_date_field(source)
        result: dict[str, Any] = {
            "source": source.summary(),
            "notes": source.notes,
            "date_field": date_field.name if date_field else None,
            "default_filters": source.default_filters,
            "field_count": len(source.fields),
        }
        if expand:
            result["fields"] = [
                {"name": f.name, "base_type": f.base_type, "semantic_type": f.semantic_type, **({"id": f.id} if f.id else {})}
                for f in source.fields
            ]
        else:
            visible = [f for f in source.fields if not f.name.startswith("_")]
            result["metrics"] = [f.name for f in visible if _is_metric_candidate(f)]
            result["dates"] = [f.name for f in visible if f.base_type in TEMPORAL_TYPES]
            result["dimensions"] = [f.name for f in visible if f.base_type in TEXT_TYPES]
            result["hint"] = "Pass expand=true for every column with types."
        return result

    async def list_kpi_sources(self, evaluate: bool = False, metric: str | None = None) -> dict[str, Any]:
        entries = [dict(s) for s in KNOWN_SOURCES]
        if not any(e["kind"] == "card" and e["id"] == self._canonical_card_id for e in entries):
            entries.insert(0, {"kind": "card", "id": self._canonical_card_id, "name": None, "role": "canonical"})
        for entry in entries:
            if entry["kind"] == "card" and entry["id"] == self._canonical_card_id:
                entry["role"] = "canonical"
            elif entry.get("role") == "canonical":
                entry["role"] = "alternative"
            entry.pop("default_filters", None)
        if evaluate:
            await asyncio.gather(*(self._evaluate_source(entry, metric) for entry in entries))
        return {
            "canonical": {"kind": "card", "id": self._canonical_card_id},
            "sources": entries,
            "criteria": ["canonical", "runnable", "kpi_suitable", "supplier_filterable"],
            "hint": None if evaluate else "Pass evaluate=true to check each source live.",
        }

    async def _evaluate_source(self, entry: dict[str, Any], metric: str | None) -> None:
        checks: dict[str, Any] = {"canonical": entry.get("role") == "canonical"}
        try:
            source = await self.load_source(entry["id"], entry["kind"])
            entry["name"] = source.name
            entry["type"] = source.source_type
            ranked = rank_metric_fields(metric, source.fields) if metric else []
            eur_metrics = [f.name for f in source.fields if _is_metric_candidate(f) and "euro" in _words(f.name)]
            checks["kpi_suitable"] = bool(ranked and ranked[0][0] >= 0.6) if metric else bool(eur_metrics)
            if metric and ranked:
                checks["metric_field"] = ranked[0][1].name
            date_field = self.resolve_date_field(source)
            checks["date_field"] = date_field.name if date_field else None
            suppliers = [f.name for f in source.fields if entity_name_score(f, "supplier") >= 0.9]
            checks["supplier_filterable"] = bool(suppliers)
            checks["supplier_fields"] = suppliers
            probe = build_queries(source, {"aggregation": [{"op": "count"}], "limit": 1})
            try:
                await self.run_dataset(probe["legacy"])
                checks["runnable"] = True
            except KpiError as e:
                checks["runnable"] = False
                checks["runnable_error"] = str(e)[:200]
        except KpiError as e:
            checks["runnable"] = False
            checks["error"] = str(e)[:200]
        entry["checks"] = checks

    # -- Profiling and entity discovery ------------------------------------------

    async def _value_counts(
        self, source: KpiSource, item: SourceField, *, search: str | None, limit: int
    ) -> list[dict[str, Any]]:
        spec: dict[str, Any] = {
            "aggregation": [{"op": "count"}],
            "breakout": [{"field": item.name}],
            "order_by": [{"aggregation": 0, "direction": "desc"}],
            "limit": limit,
        }
        if search:
            spec["filters"] = {"field": item.name, "op": "contains", "values": [search], "case_sensitive": False}
        rows = (await self.run_dataset(build_queries(source, spec)["legacy"]))["rows"]
        return [{"value": row[0], "rows": row[1]} for row in rows if row and row[0] not in (None, "")]

    async def profile_field_values(
        self,
        field_name: str,
        *,
        source_id: int | None = None,
        search: str | None = None,
        fuzzy: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 2000:
            raise KpiError("limit must be between 1 and 2000", error_type="invalid_input")
        source = await self.load_source(source_id)
        item = _resolve_field(source, field_name)
        result: dict[str, Any] = {"source": source.summary(), "field": item.name, "base_type": item.base_type}
        if search and fuzzy:
            values = await self._value_counts(source, item, search=None, limit=2000)
            scored = sorted(
                ({**v, "similarity": similarity(search, v["value"])} for v in values),
                key=lambda v: (-v["similarity"], -v["rows"]),
            )
            result["fuzzy_matches"] = [v for v in scored if v["similarity"] >= 0.6][:limit]
            result["values_scanned"] = len(values)
        else:
            values = await self._value_counts(source, item, search=search, limit=limit)
            result["top_values"] = values
            result["returned"] = len(values)
            if search:
                result["search"] = {"op": "contains", "value": search, "case_sensitive": False}
        return result

    async def discover_entity_fields(
        self,
        entity_name: str,
        *,
        entity_type: str = "supplier",
        source_id: int | None = None,
        source: KpiSource | None = None,
        max_candidates: int = 4,
        sample_limit: int = 5,
    ) -> dict[str, Any]:
        entity_name = (entity_name or "").strip()
        if not entity_name:
            raise KpiError("entity_name is required", error_type="invalid_input")
        if entity_type != "auto" and entity_type not in ENTITY_FIELD_HINTS:
            raise KpiError(
                f"Unknown entity_type {entity_type!r}; use one of {sorted(ENTITY_FIELD_HINTS)} or 'auto'",
                error_type="invalid_input",
            )
        source = source or await self.load_source(source_id)
        numeric_entity = entity_name.replace(" ", "").isdigit()
        scored = sorted(
            (
                (entity_name_score(f, entity_type, numeric_entity=numeric_entity), f)
                for f in source.fields
            ),
            key=lambda pair: -pair[0],
        )
        candidates = [(score, f) for score, f in scored if score > 0][:max_candidates]
        if not candidates:
            raise KpiError(f"No {entity_type} fields found in source {source.name!r}", error_type="no_candidate_fields")

        async def probe(score: float, item: SourceField) -> dict[str, Any]:
            entry: dict[str, Any] = {"field": item.name, "base_type": item.base_type, "name_score": score}
            try:
                matches = await self._value_counts(source, item, search=entity_name, limit=25)
            except KpiError as e:
                entry.update(match_type="error", confidence=0.0, error=str(e)[:200])
                return entry
            exact = [m for m in matches if _core_name(m["value"]) == _core_name(entity_name)]
            if exact:
                match_type, match_score, selected = "exact", 1.0, exact
            elif matches:
                match_type, selected = "contains", matches
                match_score = 0.85 if len(matches) == 1 else 0.7 if len(matches) <= 3 else 0.5
            else:
                match_type, match_score, selected = "none", 0.0, []
            entry.update(
                match_type=match_type,
                confidence=round(0.35 * score + 0.65 * match_score, 3) if match_score else 0.0,
                matched_rows=sum(m["rows"] for m in matches),
                distinct_matches=len(matches),
                truncated=len(matches) == 25,
                selected_values=[m["value"] for m in selected],
                sample_matches=matches[:sample_limit],
            )
            return entry

        results = list(await asyncio.gather(*(probe(score, item) for score, item in candidates)))
        if not any(r.get("match_type") in {"exact", "contains"} for r in results):
            for entry in results[:2]:
                if entry.get("match_type") == "error":
                    continue
                item = _resolve_field(source, entry["field"])
                try:
                    values = await self._value_counts(source, item, search=None, limit=2000)
                except KpiError as e:
                    entry["fuzzy_error"] = str(e)[:200]
                    continue
                scored_values = sorted(
                    ({**v, "similarity": similarity(entity_name, v["value"])} for v in values),
                    key=lambda v: -v["similarity"],
                )
                best = scored_values[0]["similarity"] if scored_values else 0.0
                if best >= 0.75:
                    close = [v for v in scored_values if v["similarity"] >= best - 0.05][:5]
                    entry.update(
                        match_type="fuzzy",
                        confidence=round(0.35 * entry["name_score"] + 0.65 * best * 0.8, 3),
                        matched_rows=sum(v["rows"] for v in close),
                        distinct_matches=len(close),
                        selected_values=[v["value"] for v in close],
                        sample_matches=close[:sample_limit],
                    )
                else:
                    entry["closest_values"] = scored_values[:3]

        results.sort(key=lambda r: -r.get("confidence", 0.0))
        best = next((r for r in results if r.get("match_type") in {"exact", "contains", "fuzzy"}), None)
        entity_filter = None
        warnings: list[str] = []
        if best is not None:
            if best["match_type"] == "contains" and (best["truncated"] or best["distinct_matches"] > 10):
                entity_filter = {"field": best["field"], "op": "contains", "values": [entity_name], "case_sensitive": False}
            else:
                entity_filter = {"field": best["field"], "op": "=", "values": best["selected_values"]}
            if best["match_type"] != "exact" and best["distinct_matches"] > 1:
                warnings.append(
                    f"{entity_name!r} matches {best['distinct_matches']} distinct {best['field']} values; all are included"
                )
        return {
            "entity": entity_name,
            "entity_type": entity_type,
            "source": source.summary(),
            "candidates": results,
            "best": best,
            "filter": entity_filter,
            "warnings": warnings,
        }

    # -- Validation, permissions and saved questions --------------------------

    async def validate_mbql_query(self, query: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        source = None
        try:
            if isinstance(query, dict) and query.get("type") == "query":
                table = (query.get("query") or {}).get("source-table")
                match = _CARD_SOURCE.match(table) if isinstance(table, str) else None
                if match:
                    source = await self.load_source(int(match.group(1)), "card")
                elif isinstance(table, int):
                    source = await self.load_source(table, "table")
            elif isinstance(query, dict) and query.get("stages"):
                first = query["stages"][0] if isinstance(query["stages"][0], dict) else {}
                if isinstance(first.get("source-card"), int):
                    source = await self.load_source(first["source-card"], "card")
                elif isinstance(first.get("source-table"), int):
                    source = await self.load_source(first["source-table"], "table")
        except KpiError as e:
            source = None
            source_error = str(e)[:200]
        else:
            source_error = None
        result = validate_query(query, source)
        result["source"] = source.summary() if source else None
        if source_error:
            result["warnings"].append(f"source metadata unavailable, field names not checked: {source_error}")
        if dry_run:
            if not result["valid"]:
                result["dry_run"] = {"status": "skipped", "reason": "structural validation failed"}
            elif result["format"] == "mbql5_portable":
                result["dry_run"] = {"status": "skipped", "reason": "portable queries cannot run over REST; use ditra_analytics construct tools"}
            elif result["format"] == "native":
                result["dry_run"] = {"status": "skipped", "reason": "native SQL is not dry-run; use can_run_native_query"}
            else:
                probe = copy.deepcopy(query)
                if result["format"] == "legacy":
                    probe["query"]["limit"] = 1
                elif result["format"] == "mbql5":
                    probe["stages"][-1]["limit"] = 1
                try:
                    data = await self.run_dataset(probe)
                    result["dry_run"] = {"status": "ok", "columns": data["columns"], "sample_row": data["rows"][:1]}
                except KpiError as e:
                    result["valid"] = False
                    result["dry_run"] = {"status": "failed", "error": str(e), "error_type": e.error_type}
        return result

    async def can_run_native_query(self, database_id: int | None = None, *, probe: bool = False) -> dict[str, Any]:
        if database_id is None:
            database_id = (await self.load_source()).database_id
        cached = self._native.get(database_id)
        if cached and not probe and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        fallback = (
            "Use answer_kpi / build_mbql_query (MBQL over the canonical model), a saved question "
            "via get_card_parameters + api_run_card_query, or ask a Metabase admin to grant "
            "'Create queries: Query builder and native' on this database to the service identity's group."
        )
        try:
            database = await self._database(database_id)
        except KpiError as e:
            return {"database": {"id": database_id}, "allowed": False, "status": "blocked",
                    "reason": f"Database is not accessible: {e}", "fallback": fallback}
        identity: dict[str, Any] | None
        try:
            user = await self._call("GET", "/api/user/current")
            identity = {"user_id": user.get("id"), "is_superuser": user.get("is_superuser"), "group_ids": user.get("group_ids")}
        except KpiError:
            identity = None
        permission = database.get("native_permissions")
        allowed = permission == "write"
        reason = (
            "native_permissions=write"
            if allowed
            else f"Metabase reports native_permissions={permission!r} on database {database_id} "
            f"({database.get('name')}) for the REST service identity; ad-hoc SQL needs native query permission."
        )
        result: dict[str, Any] = {
            "database": {k: database.get(k) for k in ("id", "name", "engine")},
            "allowed": allowed,
            "status": "allowed" if allowed else "blocked",
            "reason": reason,
            "identity": identity,
            "fallback": None if allowed else fallback,
        }
        if probe:
            try:
                await self.run_dataset({"database": database_id, "type": "native", "native": {"query": "SELECT 1"}})
                result["probe"] = {"status": "ok"}
                result.update(allowed=True, status="allowed", fallback=None)
            except KpiError as e:
                result["probe"] = {"status": "failed", "error_type": e.error_type, "error": str(e)[:200]}
                result.update(allowed=False, status="blocked", fallback=fallback)
                if e.error_type == "missing-required-permissions":
                    result["reason"] = f"Probe 'SELECT 1' failed with missing-required-permissions on database {database_id}."
        self._native[database_id] = (time.monotonic(), result)
        return result

    async def get_card_parameters(
        self, card_id: int, *, include_values: bool = False, values_limit: int = 50
    ) -> dict[str, Any]:
        card = await self._call("GET", f"/api/card/{card_id}")
        dataset_query = card.get("dataset_query") or {}
        tags: dict[str, Any] = dict((dataset_query.get("native") or {}).get("template-tags") or {})
        for stage in dataset_query.get("stages") or []:
            if isinstance(stage, dict):
                tags.update(stage.get("template-tags") or {})
        described: list[dict[str, Any]] = []
        seen: set[str] = set()
        for param in card.get("parameters") or []:
            tag_name = _target_tag(param.get("target"))
            if tag_name:
                seen.add(tag_name)
            described.append(_describe_parameter(param, tags.get(tag_name) if tag_name else None))
        for name, tag in tags.items():
            if name in seen or tag.get("type") in {"card", "snippet"}:
                continue
            is_dimension = tag.get("type") == "dimension"
            described.append(
                _describe_parameter(
                    {
                        "id": tag.get("id"),
                        "name": tag.get("display-name") or name,
                        "slug": name,
                        "type": tag.get("widget-type") if is_dimension else _TAG_PARAMETER_TYPES.get(tag.get("type"), "category"),
                        "target": ["dimension" if is_dimension else "variable", ["template-tag", name]],
                        "required": tag.get("required", False),
                        "default": tag.get("default"),
                    },
                    tag,
                )
            )
        if include_values:
            for param in described:
                if not param.get("id") or param["allowed_values"] is not None:
                    continue
                try:
                    values = await self._call("GET", f"/api/card/{card_id}/params/{param['id']}/values")
                    flat = [v[0] if isinstance(v, list) and v else v for v in (values or {}).get("values", [])]
                    param["allowed_values"] = flat[:values_limit]
                    param["has_more_values"] = bool((values or {}).get("has_more_values")) or len(flat) > values_limit
                except KpiError as e:
                    param["values_error"] = str(e)[:200]
        return {
            "card": {k: card.get(k) for k in ("id", "name", "type", "display", "database_id")},
            "parameter_count": len(described),
            "parameters": described,
            "example_payload": [
                {"id": p["id"], "type": p["type"], "target": p["target"], "value": f"<{p['format']}>"}
                for p in described
            ],
            "usage": "Pass card_parameters={slug: value} to answer_kpi, or fill example_payload for api_run_card_query.",
        }

    # -- KPI orchestration ---------------------------------------------------------

    async def build_mbql_query(self, spec: dict[str, Any], *, source_id: int | None = None, kind: str = "card") -> dict[str, Any]:
        source = await self.load_source(source_id, kind)
        queries = build_queries(source, spec)
        return {
            "source": source.summary(),
            **queries,
            "validation": validate_query(queries["legacy"], source),
            "usage": "Run 'legacy' with the query tool path /api/dataset (validate_mbql_query dry_run=true); "
            "use 'mbql5_portable' with ditra_analytics construct/visualize tools.",
        }

    async def answer_kpi(
        self,
        question: str | None = None,
        entity_name: str | None = None,
        timeframe: str | None = None,
        metric: str | None = None,
        *,
        entity_type: str = "supplier",
        aggregation: str = "sum",
        breakdown: str | None = "month",
        source_card_id: int | None = None,
        date_field: str | None = None,
        card_id: int | None = None,
        card_parameters: dict[str, Any] | None = None,
        apply_default_filters: bool = True,
        include_queries: bool = False,
    ) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        warnings: list[str] = []
        interpretation: dict[str, Any] = {
            "question": question, "metric": metric, "entity_name": entity_name, "timeframe": timeframe,
        }

        def invalid(reason: str, **extra: Any) -> dict[str, Any]:
            return {"status": "invalid_input", "reason": reason, "interpretation": interpretation, "attempts": attempts, **extra}

        if aggregation not in AGGREGATIONS:
            return invalid(f"aggregation must be one of {sorted(AGGREGATIONS)}")
        if breakdown in {"none", ""}:
            breakdown = None
        if breakdown is not None and breakdown not in TEMPORAL_UNITS:
            return invalid(f"breakdown must be one of {TEMPORAL_UNITS} or null")
        try:
            tf = parse_timeframe(timeframe) if timeframe else parse_timeframe(question, strict=False)
        except KpiError as e:
            return invalid(str(e))
        if tf and not timeframe:
            interpretation["timeframe_from_question"] = tf.label
        if tf is None:
            warnings.append("No timeframe recognised: aggregating over all dates.")
        if not entity_name and question:
            entity_name = extract_entity_name(question)
            if entity_name:
                interpretation["entity_from_question"] = entity_name
        metric_text = metric or question
        if not metric_text and aggregation != "count":
            return invalid("Provide metric (e.g. 'ordinato lordo iva') or a question")

        if card_id is not None:
            try:
                parameters_meta = await self.get_card_parameters(card_id)
                payload = build_card_parameter_payload(parameters_meta["parameters"], card_parameters or {})
                data = _parse_dataset(await self._call("POST", f"/api/card/{card_id}/query", json={"parameters": payload}))
                attempts.append({"strategy": "saved_card", "status": "ok", "card_id": card_id})
                rows = data["rows"]
                total = None
                if len(rows) == 1 and len(rows[0]) == 1 and isinstance(rows[0][0], (int, float)):
                    total = rows[0][0]
                return {
                    "status": "ok",
                    "strategy": "saved_card",
                    "answer": {"total": total, "columns": data["columns"], "rows": rows[:100], "row_count": data["row_count"]},
                    "source": parameters_meta["card"],
                    "parameters_applied": payload,
                    "attempts": attempts,
                    "warnings": warnings,
                    "interpretation": interpretation,
                }
            except KpiError as e:
                attempts.append({"strategy": "saved_card", "status": "failed", "card_id": card_id,
                                 "reason": str(e), "error_type": e.error_type})
        else:
            attempts.append({"strategy": "saved_card", "status": "skipped",
                             "reason": "No saved question selected (pass card_id and card_parameters to use one)."})

        try:
            source = await self.load_source(source_card_id)
        except KpiError as e:
            return {"status": "blocked", "reason": f"Source unavailable: {e}", "attempts": attempts, "interpretation": interpretation}

        metric_field: SourceField | None = None
        metric_info: dict[str, Any] | None = None
        if metric_text and not (aggregation == "count" and not metric):
            ranked = rank_metric_fields(metric_text, source.fields)
            if not ranked or ranked[0][0] < 0.6:
                return invalid(
                    f"Could not resolve metric {metric_text!r} in {source.name!r}",
                    metric_candidates=[{"field": f.name, "score": s} for s, f in ranked[:5]],
                )
            metric_field = ranked[0][1]
            metric_info = {
                "field": metric_field.name,
                "confidence": min(1.0, ranked[0][0]),
                "alternatives": [{"field": f.name, "score": min(1.0, s)} for s, f in ranked[1:4]],
            }
        try:
            date_item = self.resolve_date_field(source, date_field) if (tf or breakdown) else None
        except KpiError as e:
            return invalid(str(e))
        if (tf or breakdown) and date_item is None:
            return invalid(f"Source {source.name!r} has no temporal field for the timeframe/breakdown")

        matched: dict[str, Any] | None = None
        filters: list[dict[str, Any]] = []
        if entity_name:
            try:
                discovery = await self.discover_entity_fields(entity_name, entity_type=entity_type, source=source)
            except KpiError as e:
                return invalid(str(e))
            warnings.extend(discovery["warnings"])
            best = discovery["best"]
            probes_failed = all(c.get("match_type") == "error" for c in discovery["candidates"])
            if best is None and probes_failed:
                top = discovery["candidates"][0]
                best = {
                    "field": top["field"],
                    "match_type": "unverified",
                    "confidence": round(0.35 * top["name_score"], 3),
                    "selected_values": [entity_name],
                }
                discovery["filter"] = {
                    "field": top["field"], "op": "contains", "values": [entity_name], "case_sensitive": False,
                }
                warnings.append(
                    f"Entity values could not be verified ({top.get('error')}); using case-insensitive "
                    f"'contains' on {top['field']!r}."
                )
            if best is None:
                return {
                    "status": "no_match",
                    "reason": f"No {entity_type} value matching {entity_name!r} in {source.name!r}",
                    "candidates": discovery["candidates"],
                    "source": source.summary(),
                    "attempts": attempts,
                    "interpretation": interpretation,
                    "hint": "Check spelling or use profile_field_values(field, search=..., fuzzy=true).",
                }
            matched = {
                "field": best["field"],
                "match_type": best["match_type"],
                "confidence": best["confidence"],
                "values": best["selected_values"],
                "alternatives": [
                    {"field": c["field"], "confidence": c.get("confidence"), "match_type": c.get("match_type")}
                    for c in discovery["candidates"] if c is not best
                ],
            }
            filters.append(discovery["filter"])
        if tf and date_item:
            filters.append({"field": date_item.name, "op": "between", "values": [tf.start.isoformat(), tf.end.isoformat()]})
        default_notes: list[str] = []
        default_indexes: set[int] = set()
        if apply_default_filters:
            for default in source.default_filters:
                default_indexes.add(len(filters))
                filters.append({k: v for k, v in default.items() if k != "reason"})
                default_notes.append(f"{_describe_filter(default)} — default: {default.get('reason')}")

        agg_spec = {"op": aggregation, "field": metric_field.name if metric_field else None}
        spec: dict[str, Any] = {"aggregation": [agg_spec], "filters": {"and": filters} if filters else None}
        if breakdown and date_item:
            spec["breakout"] = [{"field": date_item.name, "temporal_unit": breakdown}]
        currency = "EUR" if metric_field and "euro" in _words(metric_field.name) else None
        filters_applied = [
            _describe_filter(f) + (" (default KPI filter)" if index in default_indexes else "")
            for index, f in enumerate(filters)
        ]

        def success(strategy: str, rows: list[Any], total_rows: list[Any] | None, query_payload: dict[str, Any]) -> dict[str, Any]:
            breakdown_rows = None
            if breakdown:
                breakdown_rows = [
                    {"period": _period_label(row[0], breakdown), "value": row[1]}
                    for row in rows if row and len(row) >= 2
                ]
                if total_rows is not None:
                    total = total_rows[0][0] if total_rows and total_rows[0] else None
                else:
                    total = sum(r["value"] for r in breakdown_rows if isinstance(r["value"], (int, float)))
            else:
                total = rows[0][0] if rows and rows[0] else None
            if total is None:
                warnings.append("No rows matched the filters; total reported as 0.")
                total = 0
            if isinstance(total, float):
                total = round(total, 2)
            answer: dict[str, Any] = {
                "metric": metric_field.name if metric_field else "count",
                "aggregation": aggregation,
                "total": total,
                "total_formatted": format_amount(float(total), currency),
                "currency": currency,
                "entity": matched["values"] if matched else None,
                "timeframe": tf.as_dict() if tf else None,
            }
            output: dict[str, Any] = {
                "status": "ok",
                "strategy": strategy,
                "answer": answer,
                "breakdown": breakdown_rows,
                "source": source.summary(),
                "filters_applied": filters_applied,
                "default_filters": default_notes,
                "matched_field": matched,
                "metric_resolution": metric_info,
                "attempts": attempts,
                "warnings": warnings,
                "interpretation": interpretation,
            }
            if include_queries:
                output["queries"] = query_payload
            return output

        try:
            queries = build_queries(source, spec)
        except KpiError as e:
            return invalid(str(e))
        validation = validate_query(queries["legacy"], source)
        if not validation["valid"]:
            attempts.append({"strategy": "dynamic_mbql", "status": "invalid", "reason": "; ".join(validation["errors"])})
        else:
            try:
                data = await self.run_dataset(queries["legacy"])
                total_rows = None
                if breakdown and aggregation not in ADDITIVE_AGGREGATIONS:
                    total_spec = {**spec, "breakout": []}
                    total_rows = (await self.run_dataset(build_queries(source, total_spec)["legacy"]))["rows"]
                attempts.append({"strategy": "dynamic_mbql", "status": "ok"})
                return success(
                    "dynamic_mbql", data["rows"], total_rows,
                    {"mbql": queries["legacy"], "mbql5_portable": queries["mbql5_portable"]},
                )
            except KpiError as e:
                attempts.append({"strategy": "dynamic_mbql", "status": "failed", "reason": str(e), "error_type": e.error_type})

        native = build_native_query(
            source,
            aggregation=aggregation,
            metric=metric_field,
            filters=filters,
            breakout_field=date_item if breakdown else None,
            breakout_unit=breakdown,
        )
        if native is None:
            attempts.append({"strategy": "native_sql", "status": "skipped", "reason": "No SQL form for this source/aggregation."})
        else:
            preflight = await self.can_run_native_query(source.database_id)
            if not preflight["allowed"]:
                attempts.append({"strategy": "native_sql", "status": "blocked", "reason": preflight["reason"]})
            else:
                try:
                    data = await self.run_dataset(native["query"])
                    total_rows = None
                    if breakdown and aggregation not in ADDITIVE_AGGREGATIONS:
                        total_native = build_native_query(
                            source, aggregation=aggregation, metric=metric_field, filters=filters,
                            breakout_field=None, breakout_unit=None,
                        )
                        total_rows = (await self.run_dataset(total_native["query"]))["rows"] if total_native else None
                    attempts.append({"strategy": "native_sql", "status": "ok"})
                    return success("native_sql", data["rows"], total_rows, {"native": native})
                except KpiError as e:
                    attempts.append({"strategy": "native_sql", "status": "failed", "reason": str(e), "error_type": e.error_type})

        reasons = [f"{a['strategy']}: {a['reason']}" for a in attempts if a["status"] in {"failed", "blocked", "invalid"}]
        return {
            "status": "blocked",
            "reason": "; ".join(reasons) or "No strategy could run",
            "attempts": attempts,
            "source": source.summary(),
            "filters_applied": filters_applied,
            "matched_field": matched,
            "metric_resolution": metric_info,
            "queries": {
                "mbql": queries["legacy"],
                "mbql5_portable": queries["mbql5_portable"],
                "native_sql": native["sql_preview"] if native else None,
                "native": native["query"] if native else None,
            },
            "warnings": warnings,
            "interpretation": interpretation,
        }
