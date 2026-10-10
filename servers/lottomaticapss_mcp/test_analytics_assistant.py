from __future__ import annotations

import asyncio
import unittest
from datetime import date
from unittest.mock import patch

from .analytics_assistant import (
    AnalyticsAssistant,
    KpiError,
    KpiSource,
    SourceField,
    build_card_parameter_payload,
    build_native_query,
    build_queries,
    extract_entity_name,
    parse_timeframe,
    rank_metric_fields,
    similarity,
    validate_query,
)
from .metabase_client import MetabaseClient, MetabaseClientError, MetabaseResult
from .settings import MetabaseSettings


def run(coro):
    return asyncio.run(coro)


ODA_FIELDS = [
    ("Conto fornitore", "type/Text"),
    ("Fornitore", "type/Text"),
    ("Importo ordinato", "type/Decimal"),
    ("Importo ordinato Netto EURO", "type/Decimal"),
    ("Ord. Lordo IVA", "type/Decimal"),
    ("Ord. Lordo IVA EURO", "type/Decimal"),
    ("RDA Tot.lordo IVA", "type/Decimal"),
    ("RDA Tot.lordo IVA2 EURO", "type/Decimal"),
    ("Descr. società", "type/Text"),
    ("data_doc_date", "type/Date"),
    ("oda_date_for_filter", "type/Date"),
    ("supplier_key", "type/Text"),
    ("is_pss_order", "type/Integer"),
    ("_sdc_sequence", "type/BigInteger"),
]
NOVACONNECT_MONTHS = [
    ["2025-01-01T00:00:00+01:00", 474301.02],
    ["2025-02-01T00:00:00+01:00", 914736.48],
    ["2025-03-01T00:00:00+01:00", 810522.48],
    ["2025-04-01T00:00:00+02:00", 4003430.0],
    ["2025-05-01T00:00:00+02:00", 330327.2],
    ["2025-06-01T00:00:00+02:00", 1058234.14],
]


def oda_source() -> KpiSource:
    return KpiSource(
        kind="card", id=685, name="model_zrep_oda_detail", database_id=2, database_name="Analytics",
        entity_id="q_7gQDR3yYx-JAlVsMqdO", source_type="model",
        fields=[SourceField(n, t) for n, t in ODA_FIELDS], role="canonical",
        date_field="oda_date_for_filter",
        default_filters=[{"field": "is_pss_order", "op": "=", "values": [1], "reason": "PSS"}],
    )


def _field_name(ref):
    return ref[1] if isinstance(ref[1], str) else ref[2]


class FakeMetabase:
    """Minimal REST fake for the ODA model (card 685, database 2)."""

    def __init__(self, native_permissions=None, fail_mbql=False):
        self.native_permissions = native_permissions
        self.fail_mbql = fail_mbql
        self.datasets: list[dict] = []

    async def __call__(self, method, path, *, params=None, json=None, **kwargs):
        if (method, path) == ("GET", "/api/card/685"):
            return {
                "id": 685, "name": "model_zrep_oda_detail", "type": "model", "database_id": 2,
                "entity_id": "q_7gQDR3yYx-JAlVsMqdO",
                "result_metadata": [{"name": n, "display_name": n, "base_type": t} for n, t in ODA_FIELDS],
            }
        if (method, path) == ("GET", "/api/database/2"):
            return {"id": 2, "name": "Analytics", "engine": "postgres", "native_permissions": self.native_permissions}
        if (method, path) == ("GET", "/api/user/current"):
            return {"id": 3, "is_superuser": False, "group_ids": [1, 5]}
        if (method, path) == ("GET", "/api/card/900"):
            return {
                "id": 900, "name": "Ordinato per fornitore", "type": "question", "database_id": 2,
                "parameters": [
                    {"id": "p-sup", "name": "Fornitore", "slug": "fornitore", "type": "string/=",
                     "target": ["dimension", ["template-tag", "fornitore"]]},
                    {"id": "p-dates", "name": "Periodo", "slug": "periodo", "type": "date/all-options",
                     "target": ["dimension", ["template-tag", "periodo"]], "required": True},
                ],
                "dataset_query": {"type": "native", "native": {"query": "select 1", "template-tags": {
                    "fornitore": {"id": "p-sup", "name": "fornitore", "type": "dimension", "widget-type": "string/="},
                    "periodo": {"id": "p-dates", "name": "periodo", "type": "dimension", "widget-type": "date/all-options"},
                    "soglia": {"id": "p-min", "name": "soglia", "display-name": "Soglia", "type": "number"},
                }}},
            }
        if (method, path) == ("POST", "/api/dataset"):
            self.datasets.append(json)
            return self.dataset(json)
        raise AssertionError(f"unexpected request {method} {path}")

    def dataset(self, body):
        if body.get("type") == "native":
            if self.native_permissions != "write":
                raise MetabaseClientError(
                    '{"error_type":"missing-required-permissions","error":"You do not have permissions to run this query.","status":"failed"}',
                    status_code=403,
                )
            return {"status": "completed", "data": {"cols": [{"name": "value"}], "rows": [[7591551.32]]}}
        if self.fail_mbql:
            raise MetabaseClientError('{"error":"boom","status":"failed"}', status_code=400)
        query = body["query"]
        breakout = query.get("breakout") or []
        agg = query["aggregation"][0]
        if agg == ["count"] and breakout:
            name = _field_name(breakout[0])
            filt = query.get("filter")
            search = filt[2].lower() if filt and filt[0] == "contains" else None
            values = {"Fornitore": [["Novaconnect srl", 310], ["Acme spa", 20]],
                      "Conto fornitore": [["1000000072", 310]],
                      "supplier_key": [["1000000072", 114]],
                      "Descr. società": [["Lottomatica", 330]]}.get(name, [])
            rows = [r for r in values if search is None or search in r[0].lower()]
            return {"status": "completed", "row_count": len(rows), "data": {"cols": [{"name": name}, {"name": "count"}], "rows": rows}}
        if breakout:
            return {"status": "completed", "row_count": 6, "data": {"cols": [{"name": "month"}, {"name": "sum"}], "rows": NOVACONNECT_MONTHS}}
        return {"status": "completed", "row_count": 1, "data": {"cols": [{"name": "sum"}], "rows": [[7591551.32]]}}


def assistant_with(fake: FakeMetabase) -> AnalyticsAssistant:
    client = MetabaseClient(MetabaseSettings(site_url="https://analytics.example.test", api_key="k"))
    client._request = fake  # type: ignore[method-assign]
    return AnalyticsAssistant(client)


class TimeframeTests(unittest.TestCase):
    def test_italian_first_months(self):
        tf = parse_timeframe("mostrami ordinato lordo iva di Novaconnect nel primi 6 mesi del 2025")
        self.assertEqual((tf.start, tf.end), (date(2025, 1, 1), date(2025, 6, 30)))

    def test_formats(self):
        cases = {
            "2025-01-01..2025-06-30": (date(2025, 1, 1), date(2025, 6, 30)),
            "2025": (date(2025, 1, 1), date(2025, 12, 31)),
            "2025-H2": (date(2025, 7, 1), date(2025, 12, 31)),
            "Q1 2024": (date(2024, 1, 1), date(2024, 3, 31)),
            "2024-02": (date(2024, 2, 1), date(2024, 2, 29)),
            "secondo trimestre 2025": (date(2025, 4, 1), date(2025, 6, 30)),
            "marzo 2025": (date(2025, 3, 1), date(2025, 3, 31)),
            "primo semestre 2025": (date(2025, 1, 1), date(2025, 6, 30)),
        }
        for text, expected in cases.items():
            tf = parse_timeframe(text)
            self.assertEqual((tf.start, tf.end), expected, text)

    def test_invalid(self):
        with self.assertRaises(KpiError):
            parse_timeframe("sometime soon")
        with self.assertRaises(KpiError):
            parse_timeframe("2025-06-30..2025-01-01")


class ResolutionTests(unittest.TestCase):
    def test_entity_extraction(self):
        self.assertEqual(
            extract_entity_name("mostrami ordinato lordo iva di Novaconnect nel primi 6 mesi del 2025"),
            "Novaconnect",
        )
        self.assertEqual(extract_entity_name("ordinato di novaconnect nel 2025"), "novaconnect")

    def test_metric_ranking_prefers_eur_gross(self):
        ranked = rank_metric_fields("mostrami ordinato lordo iva di Novaconnect", oda_source().fields)
        self.assertEqual(ranked[0][1].name, "Ord. Lordo IVA EURO")
        self.assertNotIn("is_pss_order", [f.name for _, f in ranked])

    def test_similarity_ignores_legal_suffix(self):
        self.assertEqual(similarity("Novaconnect", "Novaconnect srl"), 1.0)
        self.assertGreater(similarity("Nova Connect", "NOVACONNECT S.R.L."), 0.9)
        self.assertLess(similarity("Novaconnect", "Acme spa"), 0.5)


class QueryBuilderTests(unittest.TestCase):
    def spec(self):
        return {
            "aggregation": [{"op": "sum", "field": "Ord. Lordo IVA EURO"}],
            "filters": {"and": [
                {"field": "Fornitore", "op": "=", "values": ["Novaconnect srl"]},
                {"or": [
                    {"field": "oda_date_for_filter", "op": "between", "values": ["2025-01-01", "2025-06-30"]},
                    {"field": "Conto fornitore", "op": "contains", "values": ["1000"]},
                ]},
                {"field": "is_pss_order", "op": "=", "values": ["1"]},
            ]},
            "breakout": [{"field": "oda_date_for_filter", "temporal_unit": "month"}],
            "order_by": [{"aggregation": 0, "direction": "desc"}],
        }

    def test_generates_valid_legacy_and_mbql5(self):
        queries = build_queries(oda_source(), self.spec())
        legacy = queries["legacy"]
        self.assertEqual(legacy["query"]["source-table"], "card__685")
        self.assertEqual(legacy["query"]["aggregation"], [["sum", ["field", "Ord. Lordo IVA EURO", {"base-type": "type/Decimal"}]]])
        self.assertEqual(legacy["query"]["filter"][3], ["=", ["field", "is_pss_order", {"base-type": "type/Integer"}], 1])
        self.assertTrue(validate_query(legacy, oda_source())["valid"])
        mbql5 = queries["mbql5"]
        self.assertEqual(mbql5["stages"][0]["source-card"], 685)
        self.assertEqual(len(mbql5["stages"][0]["filters"]), 3)
        self.assertEqual(validate_query(mbql5, oda_source())["errors"], [])
        portable = queries["mbql5_portable"]
        self.assertEqual(portable["database"], "Analytics")
        self.assertEqual(portable["stages"][0]["source-card"], "q_7gQDR3yYx-JAlVsMqdO")

    def test_rejects_bad_specs(self):
        source = oda_source()
        bad = [
            {"aggregation": [{"op": "sum", "field": "Fornitore"}]},
            {"aggregation": [{"op": "sum", "field": "Ord Lordo"}]},
            {"filters": {"field": "oda_date_for_filter", "op": "between", "values": ["01/01/2025", "2025-06-30"]}},
            {"filters": {"field": "oda_date_for_filter", "op": "between", "values": ["2025-06-30", "2025-01-01"]}},
            {"filters": {"field": "is_pss_order", "op": "contains", "values": ["1"]}},
            {"breakout": [{"field": "Fornitore", "temporal_unit": "month"}]},
        ]
        for spec in bad:
            with self.assertRaises(KpiError, msg=str(spec)):
                build_queries(source, spec)

    def test_validator_catches_malformed_mbql(self):
        source = oda_source()
        result = validate_query({"database": 2, "type": "query", "query": {
            "source-table": "card__685",
            "aggregation": [["sum", ["field", "Ord. Lordo IVA", None]]],
            "filter": ["between", ["field", "oda_date_for_filter", {"base-type": "type/Date"}], "2025/01/01"],
        }}, source)
        self.assertFalse(result["valid"])
        joined = " ".join(result["errors"])
        self.assertIn("base-type", joined)
        self.assertIn("expects 2..2 values", joined)
        missing_source = validate_query({"database": 2, "lib/type": "mbql/query", "stages": [{"lib/type": "mbql.stage/mbql"}]})
        self.assertFalse(missing_source["valid"])

    def test_native_query_is_parameterised(self):
        source = oda_source()
        native = build_native_query(
            source, aggregation="sum", metric=source.get_field("Ord. Lordo IVA EURO"),
            filters=[{"field": "Fornitore", "op": "=", "values": ["O'Brien srl"]}],
            breakout_field=source.get_field("oda_date_for_filter"), breakout_unit="month",
        )
        sql = native["query"]["native"]["query"]
        self.assertIn("{{#685-model-zrep-oda-detail}}", sql)
        self.assertIn('src."Fornitore" = {{p1}}', sql)
        self.assertNotIn("O'Brien", sql)
        self.assertIn("'O''Brien srl'", native["sql_preview"])


class CardParameterTests(unittest.TestCase):
    def test_list_template_tags_match_legacy_map_metadata(self):
        fake = FakeMetabase()
        card = run(fake("GET", "/api/card/900"))
        expected = run(assistant_with(fake).get_card_parameters(900))
        tags = list(card["dataset_query"]["native"]["template-tags"].values())

        async def modern_card(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/api/card/900"))
            return {**card, "dataset_query": {"database": 2, "lib/type": "mbql/query",
                "stages": [{"lib/type": "mbql.stage/native", "template-tags": tags}]}}

        actual = run(assistant_with(modern_card).get_card_parameters(900))
        self.assertEqual(actual["parameters"], expected["parameters"])
        self.assertEqual(actual["example_payload"], expected["example_payload"])

    def test_list_template_tags_preserve_declared_defaults_and_required(self):
        async def card(method, path, **kwargs):
            return {"id": 850, "dataset_query": {"stages": [{"template-tags": [
                {"name": "category", "type": "text", "id": "category", "required": True, "default": "IT"},
                {"name": "optional", "type": "text", "id": "optional"}]}]}}

        result = run(assistant_with(card).get_card_parameters(850))
        by_slug = {param["slug"]: param for param in result["parameters"]}
        self.assertTrue(by_slug["category"]["required"])
        self.assertEqual(by_slug["category"]["default"], "IT")
        self.assertFalse(by_slug["optional"]["required"])
        self.assertIsNone(by_slug["optional"]["default"])

    def test_introspection_and_payload(self):
        assistant = assistant_with(FakeMetabase())
        result = run(assistant.get_card_parameters(900))
        by_slug = {p["slug"]: p for p in result["parameters"]}
        self.assertEqual(set(by_slug), {"fornitore", "periodo", "soglia"})
        self.assertEqual(by_slug["periodo"]["format"], "YYYY-MM-DD~YYYY-MM-DD | past3months | thisyear")
        self.assertTrue(by_slug["periodo"]["required"])
        self.assertEqual(by_slug["soglia"]["type"], "number/=")
        payload = build_card_parameter_payload(
            result["parameters"], {"Fornitore": "Novaconnect srl", "periodo": "2025-01-01~2025-06-30"}
        )
        self.assertEqual(payload[0]["value"], ["Novaconnect srl"])
        self.assertEqual(payload[1]["value"], "2025-01-01~2025-06-30")
        with self.assertRaises(KpiError):
            build_card_parameter_payload(result["parameters"], {"fornitore": "x"})
        with self.assertRaises(KpiError):
            build_card_parameter_payload(result["parameters"], {"periodo": "2025", "bogus": 1})


class AnswerKpiTests(unittest.TestCase):
    def test_novaconnect_one_pass(self):
        fake = FakeMetabase()
        result = run(assistant_with(fake).answer_kpi(
            question="mostrami ordinato lordo iva di Novaconnect nel primi 6 mesi del 2025"
        ))
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["strategy"], "dynamic_mbql")
        self.assertEqual(result["answer"]["metric"], "Ord. Lordo IVA EURO")
        self.assertEqual(result["answer"]["total"], 7591551.32)
        self.assertEqual(result["answer"]["total_formatted"], "€ 7.591.551,32")
        self.assertEqual(result["answer"]["timeframe"]["end"], "2025-06-30")
        self.assertEqual([r["period"] for r in result["breakdown"]][:2], ["2025-01", "2025-02"])
        self.assertEqual(result["matched_field"]["field"], "Fornitore")
        self.assertEqual(result["matched_field"]["values"], ["Novaconnect srl"])
        self.assertEqual(result["source"]["id"], 685)
        self.assertIn("is_pss_order = 1 (default KPI filter)", result["filters_applied"])
        executed = fake.datasets[-1]["query"]
        self.assertEqual(executed["filter"][1], ["=", ["field", "Fornitore", {"base-type": "type/Text"}], "Novaconnect srl"])

    def test_native_blocked_reports_exact_queries(self):
        result = run(assistant_with(FakeMetabase(fail_mbql=True)).answer_kpi(
            metric="ordinato lordo iva", entity_name="Novaconnect", timeframe="2025-01-01..2025-06-30",
        ))
        self.assertEqual(result["status"], "blocked", result)
        statuses = {a["strategy"]: a["status"] for a in result["attempts"]}
        self.assertEqual(statuses, {"saved_card": "skipped", "dynamic_mbql": "failed", "native_sql": "blocked"})
        self.assertIn("native_permissions=None", result["reason"])
        self.assertEqual(result["matched_field"]["match_type"], "unverified")
        self.assertIn("\"Fornitore\" ILIKE '%' || 'Novaconnect' || '%'", result["queries"]["native_sql"])
        self.assertEqual(result["queries"]["mbql"]["query"]["source-table"], "card__685")

    def test_native_fallback_when_permitted(self):
        result = run(assistant_with(FakeMetabase(native_permissions="write", fail_mbql=True)).answer_kpi(
            metric="ordinato lordo iva", entity_name="Novaconnect", timeframe="2025", breakdown=None,
        ))
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["strategy"], "native_sql")
        self.assertEqual(result["answer"]["total"], 7591551.32)

    def test_no_match_and_invalid_input(self):
        assistant = assistant_with(FakeMetabase())
        missing = run(assistant.answer_kpi(metric="ordinato lordo iva", entity_name="Zzyzx", timeframe="2025"))
        self.assertEqual(missing["status"], "no_match")
        invalid = run(assistant.answer_kpi(metric="ordinato lordo iva", timeframe="whenever"))
        self.assertEqual(invalid["status"], "invalid_input")

    def test_entity_discovery_ranks_fields(self):
        result = run(assistant_with(FakeMetabase()).discover_entity_fields("novaconnect"))
        self.assertEqual(result["best"]["field"], "Fornitore")
        self.assertEqual(result["best"]["match_type"], "exact")
        self.assertEqual(result["filter"], {"field": "Fornitore", "op": "=", "values": ["Novaconnect srl"]})
        by_code = run(assistant_with(FakeMetabase()).discover_entity_fields("1000000072"))
        self.assertIn(by_code["best"]["field"], {"Conto fornitore", "supplier_key"})

    def test_native_preflight(self):
        blocked = run(assistant_with(FakeMetabase()).can_run_native_query(2))
        self.assertFalse(blocked["allowed"])
        self.assertIn("fallback", blocked)
        allowed = run(assistant_with(FakeMetabase(native_permissions="write")).can_run_native_query(2))
        self.assertTrue(allowed["allowed"])


class DashboardKpiTests(unittest.TestCase):
    def setUp(self):
        self.client = MetabaseClient(MetabaseSettings(api_key="test"))
        self.assistant = AnalyticsAssistant(self.client)
        self.dashboard = {
            "id": 30, "name": "Lottomatica PSS Dashboard",
            "tabs": [{"id": 40, "name": "KPI"}],
            "parameters": [{"id": "d882fd37", "name": "Date Range", "slug": "date_range", "type": "date/range"}],
            "dashcards": [
                {"id": 1354, "dashboard_tab_id": 40, "card": {"id": 958, "name": "KPI | Numero Gare - PSS"},
                 "parameter_mappings": [{"parameter_id": "d882fd37", "card_id": 958,
                                         "target": ["dimension", ["field", "data_aggiudicazione_date", {"base-type": "type/Date"}], {"stage-number": 0}]}]},
                {"id": 1356, "dashboard_tab_id": 40, "card": {"id": 957, "name": "KPI | Numero Gare - Niuma"},
                 "parameter_mappings": [{"parameter_id": "d882fd37", "card_id": 957,
                                         "target": ["dimension", ["expression", "Data Aggiudicazione (Date)", {"base-type": "type/Date"}], {"stage-number": 0}]}]},
            ],
        }

    def test_runs_saved_cards_with_their_distinct_dashboard_targets(self):
        calls = []

        async def dashboard(_):
            return MetabaseResult(self.dashboard, "api")

        async def execute(dashboard_id, card_id, dashcard_id, *, parameters):
            calls.append((dashboard_id, card_id, dashcard_id, parameters))
            return MetabaseResult({"status": "completed", "data": {"cols": [{"name": "count"}],
                                                                       "rows": [[51 if card_id == 958 else 53]]}}, "api")

        with patch.object(self.client, "get_dashboard", dashboard), patch.object(
            self.client, "get_dashboard_card_data", execute
        ):
            result = run(self.assistant.answer_dashboard_kpi("Numero Gare", timeframe="2025-01-01..2026-12-31"))
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(calls), 0)

        with patch.object(self.client, "get_dashboard", dashboard), patch.object(
            self.client, "get_dashboard_card_data", execute
        ):
            pss = run(self.assistant.answer_dashboard_kpi("Numero Gare", timeframe="2025-01-01..2026-12-31", source="PSS"))
            niuma = run(self.assistant.answer_dashboard_kpi("Numero Gare", timeframe="2025-01-01..2026-12-31", source="Niuma"))
        self.assertEqual([pss["answer"]["value"], niuma["answer"]["value"]], [51, 53])
        self.assertEqual([(call[1], call[2]) for call in calls], [(958, 1354), (957, 1356)])
        self.assertEqual([call[3][0]["target"][1][0] for call in calls], ["field", "expression"])
        self.assertEqual(calls[0][3][0]["value"], "2025-01-01~2026-12-31")

    def test_missing_period_mapping_does_not_run_unfiltered_card(self):
        self.dashboard["dashcards"][0]["parameter_mappings"] = []

        async def dashboard(_):
            return MetabaseResult(self.dashboard, "api")

        async def execute(*args, **kwargs):
            raise AssertionError("Must not execute an unfiltered KPI")

        with patch.object(self.client, "get_dashboard", dashboard), patch.object(
            self.client, "get_dashboard_card_data", execute
        ):
            result = run(self.assistant.answer_dashboard_kpi("Numero Gare", timeframe="2025", source="PSS"))
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
