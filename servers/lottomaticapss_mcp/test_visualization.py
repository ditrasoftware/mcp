from __future__ import annotations

import base64
import json
import unittest

from .visualization import repair_visualization_payload

SAVED_FILTER = ["between", {"lib/uuid": "f"}, ["field", {"base-type": "type/Date"}, "data_aggiudicazione_date"],
                "2024-01-01", "2025-12-31"]
CONSTRUCTED_FILTER = ["between", {"lib/uuid": "f"}, ["field", {"base-type": "type/Date"}, "data_aggiudicazione_date"],
                      ["absolute-datetime", {"lib/uuid": "a"}, "2024-01-01", "day"],
                      ["absolute-datetime", {"lib/uuid": "b"}, "2025-12-31", "day"]]


def payload(filters, breakout=None):
    stage = {"lib/type": "mbql.stage/mbql", "source-card": 470, "filters": filters,
             "aggregation": [["distinct", {}, ["field", {}, "gara_key"]]]}
    if breakout:
        stage["breakout"] = breakout
    query = {"database": 2, "lib/type": "mbql/query", "stages": [stage]}
    raw = json.dumps(query, ensure_ascii=False).encode("utf-8")
    return {"query": base64.b64encode(raw).decode("ascii"), "prompt": "Visualize saved card 475."}


def decode(structured):
    return json.loads(base64.b64decode(structured["query"]).decode("utf-8"))


class VisualizationRepairTests(unittest.TestCase):
    def test_constructed_date_filter_restored_to_saved_literals(self):
        repaired = repair_visualization_payload(payload([CONSTRUCTED_FILTER], [["field", {}, "Società"]]))
        query = decode(repaired)
        self.assertEqual(query["stages"][0]["filters"], [SAVED_FILTER])
        self.assertEqual(query["stages"][0]["breakout"], [["field", {}, "Società"]])
        self.assertEqual(repaired["prompt"], "Visualize saved card 475.")

    def test_payload_without_constructed_dates_is_untouched(self):
        self.assertIsNone(repair_visualization_payload(payload([SAVED_FILTER])))

    def test_time_and_relative_values_are_not_rewritten(self):
        kept = [["between", {}, ["field", {}, "ts"], ["absolute-datetime", {}, "2024-01-01T10:00:00", "default"],
                 ["relative-datetime", {}, -30, "day"]]]
        self.assertIsNone(repair_visualization_payload(payload(kept)))

    def test_non_query_payloads_are_ignored(self):
        for value in (None, "text", {"prompt": "x"}, {"query": "not base64!"}, {"query": 5}):
            self.assertIsNone(repair_visualization_payload(value))


if __name__ == "__main__":
    unittest.main()
