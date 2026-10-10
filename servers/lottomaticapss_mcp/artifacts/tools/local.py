from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context

from ...rest_client import LottomaticapssAuth, LottomaticapssRestClient
from ...settings import LottomaticapssSettings
from ...metabase_client import MetabaseClient, MetabaseResult
from ...analytics_assistant import AnalyticsAssistant, KpiError
from ..resources.local import BUSINESS_SKILL_PATH
from ...gateway.connections import integration_status


def _kpi_error(e: KpiError) -> dict[str, Any]:
    return {"status": "error", "error_type": e.error_type, "reason": str(e)}


def _result_payload(key: str, result: MetabaseResult, **metadata: Any) -> dict[str, Any]:
    details = {"backend": result.backend, **metadata}
    if result.fallback_reason:
        details["reason"] = result.fallback_reason
    return {key: result.data, "_meta": details}


def _page_metadata(data: Any, limit: int, offset: int) -> dict[str, Any]:
    items = data.get("data") if isinstance(data, dict) else data
    returned = len(items) if isinstance(items, list) else None
    total = data.get("total") if isinstance(data, dict) else None
    has_more = (
        offset + returned < total
        if isinstance(returned, int) and isinstance(total, int)
        else returned == limit if returned is not None else None
    )
    return {
        "limit": limit,
        "offset": offset,
        "returned": returned,
        "total": total,
        "has_more": has_more,
        "next_offset": offset + returned if has_more and returned is not None else None,
    }


def _markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def register_local_tools(
    mcp: FastMCP,
    client: LottomaticapssRestClient,
    settings: LottomaticapssSettings,
    *,
    _ctx_or_current: Callable[[Context | None], Context | None],
    _header_auth: Callable[[Context | None], LottomaticapssAuth],
    _auth_from_args: Callable[..., LottomaticapssAuth],
    _require_auth: Callable[[LottomaticapssAuth], None],
    _apply_default_auth: Callable[..., LottomaticapssAuth],
    _coerce_positive_int: Callable[[int | str | None], int | None],
    metabase_client: MetabaseClient | None = None,
    connection_setup: Any = None,
) -> set[str]:
    """Register domain-specific local tools."""

    local_tool_names: set[str] = set()
    metabase = metabase_client or MetabaseClient(settings.metabase)
    assistant = AnalyticsAssistant(
        metabase,
        canonical_card_id=metabase.settings.kpi_source_card_id,
        date_field=metabase.settings.kpi_date_field,
    )

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False,
                          "idempotentHint": True, "openWorldHint": False})
    async def get_business_guidance() -> str:
        """Read Lottomatica PSS business guidance before procurement, KPI, visualization, or federated workflows.

        Returns the same skill published as skill://lottomatica-pss/SKILL.md.
        Use when the client cannot read MCP resources or retrieve prompts.
        """
        return BUSINESS_SKILL_PATH.read_text(encoding="utf-8")

    local_tool_names.add("get_business_guidance")

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False,
                          "idempotentHint": False, "openWorldHint": False})
    async def list_integration_connections() -> dict[str, Any]:
        """Return assigned integration states and expiring setup links for your Ditra Analytics account.

        Configured indicates stored credentials, not permission for every operation.
        An unconfigured Ditra Analytics account can start its own OAuth consent flow.
        Service connections and disabled self-service require administrator provisioning.
        """
        result = integration_status()
        if connection_setup is not None:
            from ...gateway.connections import verified_principal
            for item in result["connections"]:
                if (item["mode"] == "delegated" and item["integration"] == "ditra-analytics"
                        and item["state"] != "Configured"):
                    setup = await connection_setup.ticket(verified_principal(), item["id"])
                    item["setup_url"] = setup["setup_url"]
                    item["setup_expires_in"] = setup["expires_in"]
                    item["requested_scopes"] = setup.get("requested_scopes", [])
                    item["permission_summary"] = setup.get("permission_summary", "")
                    item["message"] = "The setup link expires after five minutes and requires the same master-login browser and separate analytics consent."
        return result

    local_tool_names.add("list_integration_connections")

    @mcp.tool()
    async def search(
        query: str,
        models: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search Ditra Analytics dashboards, questions, and collections.

        Args:
            query: Free-text search term.
            models: Optional filter, e.g. ["dashboard", "card", "collection"].
                Model filtering uses the REST augmentation.
            limit: REST page size. Supplying it selects paged REST search.
            offset: Zero-based REST result offset. A nonzero value selects REST.
        """
        result = await metabase.search(query, models=models, limit=limit, offset=offset)
        metadata: dict[str, Any] = {}
        if result.backend == "api":
            page_size, page_offset = metabase.normalize_page(limit, offset)
            metadata["page"] = _page_metadata(result.data, page_size, page_offset)
        return _result_payload("results", result, **metadata)

    local_tool_names.add("search")

    @mcp.tool()
    async def api_search(
        query: str,
        models: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search via the Ditra Analytics REST API with explicit pagination."""
        result = await metabase.api_search(
            query, models=models, limit=limit, offset=offset
        )
        page_size, page_offset = metabase.normalize_page(limit, offset)
        return _result_payload(
            "results",
            result,
            page=_page_metadata(result.data, page_size, page_offset),
        )

    local_tool_names.add("api_search")

    @mcp.tool()
    async def get_dashboard(dashboard_id: int | None = None, full: bool = False) -> dict[str, Any]:
        """Fetch a Ditra Analytics dashboard's metadata and card layout.

        Compact by default (dashboard identity, parameters, card list). Pass
        `full=true` for the complete API payload with card definitions, which
        can be very large.

        Args:
            dashboard_id: Dashboard to fetch. Defaults to the Lottomatica PSS
                Dashboard (id 30) when omitted.
            full: Return the complete, uncompacted dashboard definition.
        """
        target = dashboard_id or metabase.settings.default_dashboard_id
        result = await metabase.get_dashboard(target)
        if full or not isinstance(result.data, dict):
            return _result_payload("dashboard", result, compact=False)
        dashboard = result.data
        dashcards = dashboard.get("dashcards") or []
        compact = {
            **{k: dashboard.get(k) for k in ("id", "name", "description", "collection_id", "updated_at")},
            "tabs": [{"id": t.get("id"), "name": t.get("name")} for t in dashboard.get("tabs") or []],
            "parameters": [
                {k: p.get(k) for k in ("id", "name", "slug", "type", "default")}
                for p in dashboard.get("parameters") or []
            ],
            "cards": [
                {
                    "dashcard_id": dc.get("id"),
                    "card_id": (dc.get("card") or {}).get("id") or dc.get("card_id"),
                    "name": (dc.get("card") or {}).get("name")
                    or ((dc.get("visualization_settings") or {}).get("virtual_card") or {}).get("name"),
                    "display": (dc.get("card") or {}).get("display"),
                    "tab_id": dc.get("dashboard_tab_id"),
                }
                for dc in dashcards
            ],
            "card_count": len(dashcards),
        }
        return {
            "dashboard": compact,
            "_meta": {
                "backend": result.backend,
                "compact": True,
                "hint": "Pass full=true for complete card definitions and layout.",
            },
        }

    local_tool_names.add("get_dashboard")

    @mcp.tool()
    async def list_dashboard_cards(
        dashboard_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """List dashboard cards compactly and completely in dashboard order.

        Args:
            dashboard_id: Dashboard to inspect. Defaults to dashboard 30.
            limit: Maximum cards to return. Defaults to the configured maximum
                (500), which returns all cards in the default dashboard.
            offset: Zero-based card offset for explicit pagination.
            include_details: Include descriptions, virtual-card text, and
                parameter mappings. Defaults to false for a compact response.
        """
        target = dashboard_id or metabase.settings.default_dashboard_id
        result = await metabase.list_dashboard_cards(
            target,
            limit=limit,
            offset=offset,
            include_details=include_details,
        )
        page_size = result.data["limit"]
        page_offset = result.data["offset"]
        return {
            "dashboard": result.data["dashboard"],
            "cards": result.data["data"],
            "_meta": {
                "backend": result.backend,
                "reason": result.fallback_reason,
                "question_card_count": result.data["question_card_count"],
                "virtual_card_count": result.data["virtual_card_count"],
                "page": _page_metadata(result.data, page_size, page_offset),
            },
        }

    local_tool_names.add("list_dashboard_cards")

    @mcp.tool()
    async def list_dashboard_cards_markdown(
        dashboard_id: int | None = None,
    ) -> str:
        """Return every dashboard card as one complete Markdown table.

        Use this tool when the user asks to list all cards in a dashboard or
        asks for a Markdown table. The returned table is already fully rendered;
        present it verbatim without sampling, shortening, or summarizing rows.
        Includes saved-question cards and virtual text/heading placements.
        """
        target = dashboard_id or metabase.settings.default_dashboard_id
        result = await metabase.list_dashboard_cards(
            target,
            limit=metabase.settings.max_page_size,
            offset=0,
            include_details=True,
        )
        rows = result.data["data"]
        lines = [
            f"# Dashboard {result.data['dashboard']['id']}: "
            f"{_markdown_cell(result.data['dashboard']['name'])}",
            "",
            f"Total placements: **{result.data['total']}** "
            f"({result.data['question_card_count']} question cards, "
            f"{result.data['virtual_card_count']} virtual cards).",
            "",
            "| # | Type | Card ID | Dashcard ID | Name / text | Display | Tab ID | Row | Col | Size |",
            "|---:|---|---:|---:|---|---|---:|---:|---:|---|",
        ]
        for index, item in enumerate(rows, start=1):
            title = item.get("name") or item.get("text") or ""
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(index),
                        _markdown_cell(item.get("type")),
                        _markdown_cell(item.get("card_id")),
                        _markdown_cell(item.get("dashcard_id")),
                        _markdown_cell(title),
                        _markdown_cell(item.get("display")),
                        _markdown_cell(item.get("dashboard_tab_id")),
                        _markdown_cell(item.get("row")),
                        _markdown_cell(item.get("col")),
                        f"{_markdown_cell(item.get('size_x'))}x{_markdown_cell(item.get('size_y'))}",
                    ]
                )
                + " |"
            )
        return "\n".join(lines)

    local_tool_names.add("list_dashboard_cards_markdown")

    @mcp.tool()
    async def get_dashboard_card_data(
        dashboard_id: int,
        card_id: int,
        dashcard_id: int,
        parameters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a specific card on a Ditra Analytics dashboard and return its data.

        Args:
            dashboard_id: The dashboard containing the card.
            card_id: The underlying question/card id.
            dashcard_id: The dashboard-card placement id (from
                `get_dashboard`'s `dashcards` list).
            parameters: Optional dashboard filter values to apply.
        """
        result = await metabase.get_dashboard_card_data(
            dashboard_id, card_id, dashcard_id, parameters=parameters
        )
        return _result_payload("result", result)

    local_tool_names.add("get_dashboard_card_data")

    @mcp.tool()
    async def get_card(card_id: int) -> dict[str, Any]:
        """Fetch a Ditra Analytics saved question's metadata (query, display, columns).

        Args:
            card_id: The question/card id.
        """
        return _result_payload("card", await metabase.get_card(card_id))

    local_tool_names.add("get_card")

    @mcp.tool()
    async def api_get_card(card_id: int) -> dict[str, Any]:
        """Fetch saved-question metadata directly from the REST API."""
        return _result_payload("card", await metabase.api_get_card(card_id))

    local_tool_names.add("api_get_card")

    @mcp.tool()
    async def run_card_query(
        card_id: int, parameters: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Execute a saved Ditra Analytics question and return its result rows.

        Args:
            card_id: The question/card id to run.
            parameters: Optional filter values for parameterized questions.
        """
        return _result_payload(
            "result", await metabase.run_card_query(card_id, parameters=parameters)
        )

    local_tool_names.add("run_card_query")

    @mcp.tool()
    async def api_run_card_query(
        card_id: int, parameters: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Execute a saved question via REST, including parameter bindings."""
        return _result_payload(
            "result",
            await metabase.api_run_card_query(card_id, parameters=parameters),
        )

    local_tool_names.add("api_run_card_query")

    @mcp.tool()
    async def run_native_query(
        database_id: int,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run an ad-hoc native (SQL) query against a Ditra Analytics database.

        Args:
            database_id: The Ditra Analytics database id to query.
            query: The native SQL query text.
            parameters: Optional query parameter bindings.
        """
        return _result_payload(
            "result", await metabase.run_native_query(database_id, query, parameters=parameters)
        )

    local_tool_names.add("run_native_query")

    @mcp.tool()
    async def api_run_native_query(
        database_id: int,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute native SQL directly through the REST API."""
        return _result_payload(
            "result",
            await metabase.api_run_native_query(
                database_id, query, parameters=parameters
            ),
        )

    local_tool_names.add("api_run_native_query")

    @mcp.tool()
    async def list_collection_items(
        collection_id: int | None = None,
        models: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List dashboards/questions inside a Ditra Analytics collection.

        Args:
            collection_id: Collection to list. Defaults to the Lottomatica PSS
                Analytics collection (id 6) when omitted.
            models: Optional filter, e.g. ["dashboard", "card"].
            limit: Page size, from 1 through the configured maximum.
            offset: Zero-based result offset for fetching subsequent pages.
        """
        target = collection_id or metabase.settings.default_collection_id
        result = await metabase.list_collection_items(
            target, models=models, limit=limit, offset=offset
        )
        page_size, page_offset = metabase.normalize_page(limit, offset)
        return _result_payload(
            "items",
            result,
            page=_page_metadata(result.data, page_size, page_offset),
        )

    local_tool_names.add("list_collection_items")

    @mcp.tool()
    async def query(
        query: dict[str, Any] | None = None,
        query_handle: str | None = None,
        continuation_token: str | None = None,
    ) -> dict[str, Any]:
        """Execute or continue a paged Ditra Analytics MCP query.

        Supply exactly one of a Metabase MBQL query, a query handle returned by
        a construct operation, or a continuation token returned by this tool.
        Native MCP query pages contain up to 200 rows and continue up to the
        server's 2,000-row budget.
        """
        supplied = sum(
            value is not None for value in (query, query_handle, continuation_token)
        )
        if supplied != 1:
            raise ValueError(
                "Supply exactly one of query, query_handle, or continuation_token"
            )
        return _result_payload(
            "result",
            await metabase.query(
                query=query,
                query_handle=query_handle,
                continuation_token=continuation_token,
            ),
        )

    local_tool_names.add("query")

    # -- KPI answering layer ------------------------------------------------

    @mcp.tool()
    async def answer_dashboard_kpi(
        kpi_name: str,
        timeframe: str | None = None,
        source: str | None = None,
        dashboard_id: int | None = None,
        tab_name: str = "KPI",
        card_id: int | None = None,
        period_parameter: str = "date_range",
    ) -> dict[str, Any]:
        """Answer a saved dashboard KPI using its exact card and global period mapping. Use FIRST for dashboard KPIs.

        For "Numero Gare", specify source="PSS" or source="Niuma" (or a
        card_id). The 2025-2026 period is "2025-01-01..2026-12-31". Fetches
        the dashboard and executes the selected card in dashboard context;
        never substitutes a model count or guesses a date column. When the
        KPI/source is ambiguous, returns candidates without running a query.
        Dashboard browser filter values are not visible here: pass the period
        explicitly, and use the returned card, mapping, and period as evidence.
        """
        try:
            return await assistant.answer_dashboard_kpi(
                kpi_name, timeframe=timeframe, source=source, dashboard_id=dashboard_id,
                tab_name=tab_name, card_id=card_id, period_parameter=period_parameter,
            )
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("answer_dashboard_kpi")

    @mcp.tool()
    async def answer_kpi(
        question: str | None = None,
        entity_name: str | None = None,
        timeframe: str | None = None,
        metric: str | None = None,
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
        """Answer an ad hoc procurement KPI from a chosen model, not a saved dashboard KPI.

        For KPIs shown on a dashboard (e.g. Numero Gare PSS/Niuma), use
        answer_dashboard_kpi instead so the saved card's distinct key, filters,
        and mapped global period are preserved. This tool infers a model date
        field and may disagree with a dashboard tile.

        Example: "mostrami ordinato lordo iva di Novaconnect nei primi 6 mesi
        del 2025" -> metric="ordinato lordo iva", entity_name="Novaconnect",
        timeframe="2025-01-01..2025-06-30" (or "primi 6 mesi del 2025").

        Resolves the metric column, the supplier field and exact values, and
        the date field on the canonical ODA model, then runs the query with this
        fallback chain: saved question (when card_id is given) -> dynamic MBQL
        -> native SQL (only if permitted) -> blocked with the exact query text.
        Returns the total, an optional period breakdown, the source, the filters
        applied, the matched field, and every attempt made.

        Args:
            question: Natural-language question; used to infer missing arguments.
            entity_name: Entity to filter on (e.g. a supplier name or code).
            timeframe: YYYY-MM-DD..YYYY-MM-DD, YYYY, YYYY-H1, YYYY-Q2, YYYY-MM,
                or phrases such as "primi 6 mesi del 2025".
            metric: Measure name, e.g. "ordinato lordo iva" or "Ord. Lordo IVA EURO".
            entity_type: supplier (default), company, cost_center, wbs,
                material_group, category, user, or auto.
            aggregation: sum (default), avg, min, max, count, distinct.
            breakdown: month (default), day, week, quarter, year, or null.
            source_card_id: Override the canonical source model/question id.
            date_field: Override the date column used for timeframe/breakdown.
            card_id: Try this saved question first with card_parameters.
            card_parameters: {parameter slug|name|id: value} for card_id.
            apply_default_filters: Apply source KPI defaults (is_pss_order = 1).
            include_queries: Include the executed MBQL / SQL in the response.
        """
        try:
            return await assistant.answer_kpi(
                question=question,
                entity_name=entity_name,
                timeframe=timeframe,
                metric=metric,
                entity_type=entity_type,
                aggregation=aggregation,
                breakdown=breakdown,
                source_card_id=source_card_id,
                date_field=date_field,
                card_id=card_id,
                card_parameters=card_parameters,
                apply_default_filters=apply_default_filters,
                include_queries=include_queries,
            )
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("answer_kpi")

    @mcp.tool()
    async def discover_entity_fields(
        entity_name: str,
        entity_type: str = "supplier",
        source_card_id: int | None = None,
        max_candidates: int = 4,
        sample_limit: int = 5,
    ) -> dict[str, Any]:
        """Rank the fields that identify an entity and show real matching values.

        For suppliers it probes Fornitore, Conto fornitore, supplier_key and
        similar columns, returning per-field confidence, match type (exact,
        contains, fuzzy, none), matched row counts, sample matches, and a
        ready-to-use `filter` for build_mbql_query.
        """
        try:
            return await assistant.discover_entity_fields(
                entity_name,
                entity_type=entity_type,
                source_id=source_card_id,
                max_candidates=max(1, min(max_candidates, 10)),
                sample_limit=max(1, min(sample_limit, 25)),
            )
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("discover_entity_fields")

    @mcp.tool()
    async def build_mbql_query(
        aggregation: list[dict[str, Any]] | None = None,
        filters: dict[str, Any] | None = None,
        breakout: list[dict[str, Any]] | None = None,
        order_by: list[dict[str, Any]] | None = None,
        limit: int | None = None,
        source_id: int | None = None,
        source_kind: str = "card",
    ) -> dict[str, Any]:
        """Generate valid, typed MBQL from a simple spec (no hand-written MBQL).

        Fields are referenced by column name and typed from source metadata.
        Returns REST-executable legacy MBQL, MBQL 5, and portable MBQL 5 for
        the ditra_analytics construct/visualize tools, plus validation.

        Args:
            aggregation: e.g. [{"op": "sum", "field": "Ord. Lordo IVA EURO"}].
            filters: Tree of {"field", "op", "values"} leaves and
                {"and": [...]}, {"or": [...]}, {"not": {...}} nodes. Ops: =, !=,
                <, >, <=, >=, between, contains, does-not-contain, starts-with,
                ends-with, is-null, not-null. Dates are YYYY-MM-DD.
            breakout: e.g. [{"field": "oda_date_for_filter", "temporal_unit": "month"}].
            order_by: e.g. [{"aggregation": 0, "direction": "desc"}] or
                [{"field": "Fornitore", "direction": "asc"}].
            limit: Optional row limit.
            source_id: Card/model id (default canonical ODA model) or table id.
            source_kind: "card" (default) or "table".
        """
        spec = {"aggregation": aggregation, "filters": filters, "breakout": breakout,
                "order_by": order_by, "limit": limit}
        try:
            return await assistant.build_mbql_query(spec, source_id=source_id, kind=source_kind)
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("build_mbql_query")

    @mcp.tool()
    async def validate_mbql_query(query: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
        """Validate legacy MBQL or MBQL 5 before running it, with an optional dry run.

        Checks source-table/source-card, typed field refs against source
        metadata, temporal literal format, operator arity, and/or/not trees,
        aggregation placement, and lib/uuid presence. dry_run executes the
        query with limit 1 and reports the exact Metabase error on failure.
        """
        try:
            return await assistant.validate_mbql_query(query, dry_run=dry_run)
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("validate_mbql_query")

    @mcp.tool()
    async def can_run_native_query(database_id: int | None = None, probe: bool = False) -> dict[str, Any]:
        """Preflight native SQL permission: allowed/blocked, reason, and fallback.

        Args:
            database_id: Database to check (default: the canonical source's database).
            probe: Also execute `SELECT 1` to confirm the permission live.
        """
        try:
            return await assistant.can_run_native_query(database_id, probe=probe)
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("can_run_native_query")

    @mcp.tool()
    async def get_card_parameters(
        card_id: int, include_values: bool = False, values_limit: int = 50
    ) -> dict[str, Any]:
        """Introspect a saved question's parameters so ids are never guessed.

        Returns each parameter's id, name, slug, type, widget type, target,
        required flag, default, value format, and allowed values when static or
        when include_values=true, plus an example payload for api_run_card_query.
        """
        try:
            return await assistant.get_card_parameters(
                card_id, include_values=include_values, values_limit=max(1, min(values_limit, 500))
            )
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("get_card_parameters")

    @mcp.tool()
    async def profile_field_values(
        field: str,
        search: str | None = None,
        fuzzy: bool = False,
        limit: int = 20,
        source_card_id: int | None = None,
    ) -> dict[str, Any]:
        """Profile a column: top values with row counts, or matches for a search.

        With search, returns case-insensitive 'contains' matches; with
        fuzzy=true, scores every distinct value (up to 2000) by similarity,
        ignoring legal suffixes such as srl/spa (e.g. "Nova Connect" ->
        "Novaconnect srl").
        """
        try:
            return await assistant.profile_field_values(
                field, source_id=source_card_id, search=search, fuzzy=fuzzy, limit=limit
            )
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("profile_field_values")

    @mcp.tool()
    async def list_kpi_sources(evaluate: bool = False, metric: str | None = None) -> dict[str, Any]:
        """List candidate ODA sources and which one is canonical for KPIs.

        With evaluate=true, checks each live for runnable, kpi_suitable (has the
        metric or EUR amounts), supplier_filterable, and the date field.
        """
        try:
            return await assistant.list_kpi_sources(evaluate=evaluate, metric=metric)
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("list_kpi_sources")

    @mcp.tool()
    async def describe_kpi_source(
        source_id: int | None = None, source_kind: str = "card", expand: bool = False
    ) -> dict[str, Any]:
        """Describe a KPI source compactly: metrics, dates, dimensions, defaults.

        Defaults to the canonical ODA model. Pass expand=true for every column
        with its type.
        """
        try:
            return await assistant.describe_source(source_id, source_kind, expand)
        except KpiError as e:
            return _kpi_error(e)

    local_tool_names.add("describe_kpi_source")

    return local_tool_names
