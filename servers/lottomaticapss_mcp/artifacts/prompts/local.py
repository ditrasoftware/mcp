from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ...settings import LottomaticapssSettings


def register_local_prompts(mcp: FastMCP, settings: LottomaticapssSettings | None = None) -> dict[str, Any]:
    """Register domain-specific prompts."""

    local_prompt_registry: dict[str, Any] = {}
    mb = settings.metabase if settings else None
    dashboard_id = mb.default_dashboard_id if mb else 30
    collection_id = mb.default_collection_id if mb else 6

    @mcp.prompt()
    async def getting_started() -> str:
        """Getting started guide for the Ditra Analytics tools."""
        return f"""# Ditra Analytics — Getting Started

## Overview

These tools connect to the Ditra Analytics platform (the Lottomatica PSS
procurement dashboards) so an agent can search, inspect, and query the same
dashboards/questions shown in the Ditra Analytics Procurement Portal.

## Key identifiers

- Default dashboard: **Lottomatica PSS Dashboard** (id `{dashboard_id}`).
- Default collection: **Lottomatica PSS Analytics** (id `{collection_id}`).

## Next steps

0. For a KPI on the dashboard, call `answer_dashboard_kpi` first with the
   KPI name, an explicit period, and the source when there are multiple cards.
   It executes the saved question through its dashboard placement and uses
   that placement's global period mapping. Never use model counts or inferred
   date fields as a substitute for dashboard KPI values. If there is no
   unique match or mapped filter, report the ambiguity rather than guessing.
   For ad hoc procurement KPIs (e.g. "ordinato lordo IVA di Novaconnect nei
   primi 6 mesi del 2025"), use `answer_kpi`. It resolves the metric, supplier
   field, and timeframe on the canonical ODA model. Building blocks:
   `discover_entity_fields`, `profile_field_values`, `build_mbql_query`,
   `validate_mbql_query`, `can_run_native_query`, `get_card_parameters`,
   `list_kpi_sources`, `describe_kpi_source`. Never hand-write MBQL or guess
   parameter ids.
1. `search` — MCP-first discovery; use `api_search` for explicit pages/model filters.
2. `list_dashboard_cards_markdown` — return all cards as a finished Markdown
   table. Use `list_dashboard_cards` for structured results; `get_dashboard`
   is compact unless `full=true`.
3. `get_dashboard_card_data` — pull live data for one card when its dashboard
   parameter targets have already been inspected. Direct saved-card execution
   does not apply dashboard browser filter values automatically.
4. `run_card_query` — MCP-first saved-question execution; `api_run_card_query`
   supports REST parameter bindings.
5. `run_native_query` — MCP-first SQL execution; `api_run_native_query` is the
   explicit REST equivalent.
6. `query` — execute or continue native MCP result pages.
7. `list_collection_items` — browse REST pages with `limit` and `offset`.

## Resources

- `ditra-analytics://config` — connection configuration (non-secret).
- `ditra-analytics://dashboard-summary` — quick summary of the default dashboard.
"""

    local_prompt_registry["getting_started"] = "getting_started"

    @mcp.prompt()
    async def explore_dashboard_workflow() -> str:
        """Workflow guide for exploring a Ditra Analytics procurement dashboard."""
        return f"""# Explore a Ditra Analytics Dashboard

1. `list_dashboard_cards` with `dashboard_id={dashboard_id}` to list all cards
   without the oversized full dashboard payload.
2. For each card of interest, note its `card_id` and the dashboard-card's
   `id` (the `dashcard_id`) from the returned `dashcards` list.
3. For a saved dashboard KPI with a period, use `answer_dashboard_kpi` to
   select the tab placement, apply its mapped period target, and run the card.
   For other cards, inspect `get_dashboard(full=true)` to obtain their exact
   `parameter_mappings` before using `get_dashboard_card_data` with
   `dashboard_id`, `card_id`, `dashcard_id`, and `parameters`.
4. To explore a question outside a dashboard, use `get_card`
   for its definition and `run_card_query` to execute it.
5. For open-ended analysis, use `run_native_query` with a
   SQL query against the appropriate `database_id`.
"""

    local_prompt_registry["explore_dashboard_workflow"] = "explore_dashboard_workflow"

    return local_prompt_registry
