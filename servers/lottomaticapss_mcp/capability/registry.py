"""Capability registry for lottomaticapss_mcp.

Defines local capability contracts exposed by this MCP, including the
Ditra Analytics (Metabase) discovery/query tools.
"""

from __future__ import annotations

from .contracts import CapabilityContract
from ..version import __version__

_VERSION = __version__


def _kpi_contract(tool_name: str, description: str, properties: dict, required: list[str] | None = None,
                  tier: str = "tier_b") -> CapabilityContract:
    return CapabilityContract(
        capability_id=f"local.analytics.{tool_name}",
        tool_name=tool_name,
        version=_VERSION,
        description=description,
        input_schema={"type": "object", "properties": properties, "required": required or []},
        output_schema={"type": "object"},
        auth_profile="none",
        reliability_tier=tier,
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    )


_KPI_CAPABILITIES = [
    _kpi_contract(
        "answer_dashboard_kpi",
        "Execute a saved dashboard KPI using its mapped global period filter",
        {
            "kpi_name": {"type": "string"},
            "timeframe": {"type": ["string", "null"]},
            "source": {"type": ["string", "null"]},
            "dashboard_id": {"type": ["integer", "null"]},
            "tab_name": {"type": "string"},
            "card_id": {"type": ["integer", "null"]},
            "period_parameter": {"type": "string"},
        },
        ["kpi_name"],
        tier="tier_c",
    ),
    _kpi_contract(
        "answer_kpi",
        "Answer a procurement KPI question with verified execution and fallbacks",
        {
            "question": {"type": ["string", "null"]},
            "entity_name": {"type": ["string", "null"]},
            "timeframe": {"type": ["string", "null"]},
            "metric": {"type": ["string", "null"]},
            "breakdown": {"type": ["string", "null"]},
        },
        tier="tier_c",
    ),
    _kpi_contract(
        "discover_entity_fields",
        "Rank entity-identifying fields with confidence and sample matches",
        {"entity_name": {"type": "string"}, "entity_type": {"type": "string"}},
        ["entity_name"],
    ),
    _kpi_contract(
        "build_mbql_query",
        "Generate typed, validated MBQL from a simple spec",
        {"aggregation": {"type": ["array", "null"]}, "filters": {"type": ["object", "null"]},
         "breakout": {"type": ["array", "null"]}},
    ),
    _kpi_contract(
        "validate_mbql_query",
        "Validate MBQL structure and optionally dry-run it",
        {"query": {"type": "object"}, "dry_run": {"type": "boolean"}},
        ["query"],
    ),
    _kpi_contract(
        "can_run_native_query",
        "Preflight native SQL permission with reason and fallback",
        {"database_id": {"type": ["integer", "null"]}, "probe": {"type": "boolean"}},
    ),
    _kpi_contract(
        "get_card_parameters",
        "Introspect saved-question parameters (ids, types, formats, values)",
        {"card_id": {"type": "integer"}, "include_values": {"type": "boolean"}},
        ["card_id"],
    ),
    _kpi_contract(
        "profile_field_values",
        "Profile top values of a field and fuzzy-match a search term",
        {"field": {"type": "string"}, "search": {"type": ["string", "null"]}, "fuzzy": {"type": "boolean"}},
        ["field"],
    ),
    _kpi_contract(
        "list_kpi_sources",
        "List candidate ODA sources and the canonical KPI source",
        {"evaluate": {"type": "boolean"}, "metric": {"type": ["string", "null"]}},
    ),
    _kpi_contract(
        "describe_kpi_source",
        "Describe a KPI source compactly, expandable to all columns",
        {"source_id": {"type": ["integer", "null"]}, "expand": {"type": "boolean"}},
    ),
]

CAPABILITIES: dict[str, CapabilityContract] = {
    "local.analytics.search": CapabilityContract(
        capability_id="local.analytics.search",
        tool_name="search",
        version=_VERSION,
        description="Search Ditra Analytics dashboards, questions, and collections",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "models": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": ["integer", "null"]},
                "offset": {"type": "integer"},
                "include_details": {"type": "boolean"},
            },
            "required": ["query"],
        },
        output_schema={"type": "object", "properties": {"results": {"type": ["array", "object"]}}},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.api_search": CapabilityContract(
        capability_id="local.analytics.api_search",
        tool_name="api_search",
        version=_VERSION,
        description="Search Ditra Analytics through the paged REST API",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        output_schema={"type": "object"},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.get_dashboard": CapabilityContract(
        capability_id="local.analytics.get_dashboard",
        tool_name="get_dashboard",
        version=_VERSION,
        description="Fetch a Ditra Analytics dashboard's metadata and card layout",
        input_schema={
            "type": "object",
            "properties": {"dashboard_id": {"type": ["integer", "null"]}, "full": {"type": "boolean"}},
        },
        output_schema={"type": "object", "properties": {"dashboard": {"type": "object"}}},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["NOT_FOUND_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.list_dashboard_cards": CapabilityContract(
        capability_id="local.analytics.list_dashboard_cards",
        tool_name="list_dashboard_cards",
        version=_VERSION,
        description="List dashboard cards compactly and completely in dashboard order",
        input_schema={
            "type": "object",
            "properties": {
                "dashboard_id": {"type": ["integer", "null"]},
                "limit": {"type": ["integer", "null"]},
                "offset": {"type": "integer"},
            },
        },
        output_schema={"type": "object"},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["NOT_FOUND_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.list_dashboard_cards_markdown": CapabilityContract(
        capability_id="local.analytics.list_dashboard_cards_markdown",
        tool_name="list_dashboard_cards_markdown",
        version=_VERSION,
        description="Return every dashboard card as one complete Markdown table",
        input_schema={
            "type": "object",
            "properties": {"dashboard_id": {"type": ["integer", "null"]}},
        },
        output_schema={"type": "string"},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["NOT_FOUND_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.get_dashboard_card_data": CapabilityContract(
        capability_id="local.analytics.get_dashboard_card_data",
        tool_name="get_dashboard_card_data",
        version=_VERSION,
        description="Run a specific card on a Ditra Analytics dashboard and return its data",
        input_schema={
            "type": "object",
            "properties": {
                "dashboard_id": {"type": "integer"},
                "card_id": {"type": "integer"},
                "dashcard_id": {"type": "integer"},
                "parameters": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["dashboard_id", "card_id", "dashcard_id"],
        },
        output_schema={"type": "object", "properties": {"result": {"type": "object"}}},
        auth_profile="none",
        reliability_tier="tier_c",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.get_card": CapabilityContract(
        capability_id="local.analytics.get_card",
        tool_name="get_card",
        version=_VERSION,
        description="Fetch a Ditra Analytics saved question's metadata (query, display, columns)",
        input_schema={"type": "object", "properties": {"card_id": {"type": "integer"}}, "required": ["card_id"]},
        output_schema={"type": "object", "properties": {"card": {"type": "object"}}},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["NOT_FOUND_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.run_card_query": CapabilityContract(
        capability_id="local.analytics.run_card_query",
        tool_name="run_card_query",
        version=_VERSION,
        description="Execute a saved Ditra Analytics question and return its result rows",
        input_schema={
            "type": "object",
            "properties": {
                "card_id": {"type": "integer"},
                "parameters": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["card_id"],
        },
        output_schema={"type": "object", "properties": {"result": {"type": "object"}}},
        auth_profile="none",
        reliability_tier="tier_c",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.run_native_query": CapabilityContract(
        capability_id="local.analytics.run_native_query",
        tool_name="run_native_query",
        version=_VERSION,
        description="Run an ad-hoc native (SQL) query against a Ditra Analytics database",
        input_schema={
            "type": "object",
            "properties": {
                "database_id": {"type": "integer"},
                "query": {"type": "string"},
                "parameters": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["database_id", "query"],
        },
        output_schema={"type": "object", "properties": {"result": {"type": "object"}}},
        auth_profile="none",
        reliability_tier="tier_c",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.list_collection_items": CapabilityContract(
        capability_id="local.analytics.list_collection_items",
        tool_name="list_collection_items",
        version=_VERSION,
        description="List dashboards/questions inside a Ditra Analytics collection",
        input_schema={
            "type": "object",
            "properties": {
                "collection_id": {"type": ["integer", "null"]},
                "models": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": ["integer", "null"]},
                "offset": {"type": "integer"},
            },
        },
        output_schema={"type": "object", "properties": {"items": {"type": ["array", "object"]}}},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["NOT_FOUND_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.api_get_card": CapabilityContract(
        capability_id="local.analytics.api_get_card",
        tool_name="api_get_card",
        version=_VERSION,
        description="Fetch saved-question metadata directly from the REST API",
        input_schema={"type": "object", "properties": {"card_id": {"type": "integer"}}, "required": ["card_id"]},
        output_schema={"type": "object"},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["NOT_FOUND_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.api_run_card_query": CapabilityContract(
        capability_id="local.analytics.api_run_card_query",
        tool_name="api_run_card_query",
        version=_VERSION,
        description="Execute a saved question directly through the REST API",
        input_schema={"type": "object", "properties": {"card_id": {"type": "integer"}}, "required": ["card_id"]},
        output_schema={"type": "object"},
        auth_profile="none",
        reliability_tier="tier_c",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.api_run_native_query": CapabilityContract(
        capability_id="local.analytics.api_run_native_query",
        tool_name="api_run_native_query",
        version=_VERSION,
        description="Execute native SQL directly through the REST API",
        input_schema={"type": "object", "properties": {"database_id": {"type": "integer"}, "query": {"type": "string"}}, "required": ["database_id", "query"]},
        output_schema={"type": "object"},
        auth_profile="none",
        reliability_tier="tier_c",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
    "local.analytics.query": CapabilityContract(
        capability_id="local.analytics.query",
        tool_name="query",
        version=_VERSION,
        description="Execute or continue a paged native Metabase MCP query",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        auth_profile="none",
        reliability_tier="tier_b",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR", "TIMEOUT_ERROR"],
    ),
}

CAPABILITIES.update({contract.capability_id: contract for contract in _KPI_CAPABILITIES})


def load_capability_registry() -> dict[str, CapabilityContract]:
    """Load and validate capability registry.

    In production, this might load from a JSON configuration file, database,
    or remote registry service. For now, returns the hardcoded CAPABILITIES.
    """

    for cap_id, contract in CAPABILITIES.items():
        warnings = contract.validate()
        if warnings:
            print(f"Warning: capability {cap_id} has issues: {warnings}")

    return CAPABILITIES


def get_capability(capability_id: str) -> CapabilityContract | None:
    """Look up a capability by ID."""
    return CAPABILITIES.get(capability_id)


def get_capabilities_by_provider(provider: str | None) -> list[CapabilityContract]:
    """Get all capabilities from a provider (or local if provider is None)."""
    return [c for c in CAPABILITIES.values() if c.provider == provider]


def get_local_capabilities() -> list[CapabilityContract]:
    """Get all locally-implemented capabilities."""
    return [c for c in CAPABILITIES.values() if c.is_local]
