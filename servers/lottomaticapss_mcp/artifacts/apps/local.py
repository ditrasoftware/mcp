from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ...rest_client import LottomaticapssRestClient
from ...settings import LottomaticapssSettings


def create_local_app_providers(
    client: LottomaticapssRestClient,
    settings: LottomaticapssSettings,
) -> tuple[list[Any], dict[str, Any]]:
    """Create the Ditra Analytics app catalog entry.

    NOTE: `prefab_ui.PrefabApp` is a UI-rendering view spec (title, component
    tree, css/theme/scripts) — it has no `tools`/`resources` fields, so it
    cannot be used as a tool/resource catalog. Until a real Prefab UI view is
    built for this dashboard, the catalog below is plain metadata (not a
    FastMCP `Provider`, so `app_providers` stays empty and nothing is passed
    to `FastMCP(providers=...)`).
    """

    app_providers: list[Any] = []
    local_app_registry: dict[str, Any] = {
        "analytics_dashboard": {
            "title": "Ditra Analytics",
            "description": "Search, inspect, and query the Lottomatica PSS procurement dashboards in Ditra Analytics.",
            "tools": [
                "answer_kpi",
                "discover_entity_fields",
                "build_mbql_query",
                "validate_mbql_query",
                "can_run_native_query",
                "get_card_parameters",
                "profile_field_values",
                "list_kpi_sources",
                "describe_kpi_source",
                "search",
                "api_search",
                "get_dashboard",
                "list_dashboard_cards",
                "list_dashboard_cards_markdown",
                "get_dashboard_card_data",
                "get_card",
                "api_get_card",
                "run_card_query",
                "api_run_card_query",
                "run_native_query",
                "api_run_native_query",
                "query",
                "list_collection_items",
            ],
            "resources": [
                "ditra-analytics://config",
                "ditra-analytics://dashboard-summary",
            ],
        }
    }

    return app_providers, local_app_registry
