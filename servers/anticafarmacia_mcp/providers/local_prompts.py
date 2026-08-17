from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def register_local_prompts(mcp: FastMCP) -> dict[str, Any]:
    """Register AnticaFarmacia prompt templates."""

    @mcp.prompt()
    def anticafarmacia_patient_intake(notes: str, tenant_id: str = "") -> str:
        """Build a structured patient-intake summary from free text notes."""
        tenant_hint = tenant_id.strip() or "unknown-tenant"
        return (
            "You are assisting AnticaFarmacia intake operations.\n"
            f"Tenant context: {tenant_hint}.\n"
            "Convert the notes into JSON with these keys: patient, prescription, logistics, risks, follow_up_questions.\n"
            "Keep medical terms verbatim and flag any missing mandatory fields.\n"
            "Input notes:\n"
            f"{notes}"
        )

    @mcp.prompt()
    def anticafarmacia_order_planner(order_request: str) -> str:
        """Plan a safe order workflow from user-provided request details."""
        return (
            "You are planning an order workflow for AnticaFarmacia.\n"
            "Return:\n"
            "1) validation checklist\n"
            "2) suggested API calls in execution order\n"
            "3) rollback or correction strategy\n"
            "4) tenant and auth checks\n"
            "Request:\n"
            f"{order_request}"
        )

    @mcp.prompt()
    def anticafarmacia_gateway_route_review(tool_name: str, user_goal: str = "") -> str:
        """Guide route-policy decisions for local-vs-remote tool execution."""
        return (
            "Review gateway routing for AnticaFarmacia MCP.\n"
            f"Tool candidate: {tool_name}.\n"
            f"Goal: {user_goal or 'not provided'}.\n"
            "Output a concise decision with: route(local/remote), reason, required auth, and tenant impact."
        )

    return {
        "names": [
            "anticafarmacia_patient_intake",
            "anticafarmacia_order_planner",
            "anticafarmacia_gateway_route_review",
        ]
    }
