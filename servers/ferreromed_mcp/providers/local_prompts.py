from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..prompts.templates import register_prompts


def register_local_prompts(mcp: FastMCP) -> dict[str, Any]:
    """Register local prompt templates and return prompt metadata."""

    register_prompts(mcp)
    return {
        "names": [
            "ferreromed_patient_triage",
            "ferreromed_create_order_from_notes",
            "ferreromed_quotation_decision",
            "ferreromed_asl_lookup_helper",
            "ferreromed_asl_business_summary",
            "ferreromed_asl_data_quality_check",
            "ferreromed_maps_gather_and_map",
        ]
    }
