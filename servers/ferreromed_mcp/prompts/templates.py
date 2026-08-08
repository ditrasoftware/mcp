from __future__ import annotations

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(name="ferreromed_patient_triage")
    def patient_triage_prompt(symptoms_or_request: str) -> str:
        """Generate a structured triage checklist for a FerreroMed patient-related request."""
        return (
            "You are an assistant using the FerreroMed MCP tools.\n\n"
            "Goal: help the operator resolve a patient-related request safely and efficiently.\n\n"
            "Steps:\n"
            "1) Ask for patient identifiers (tax_id, full name, city) if missing.\n"
            "2) Use `patients_list` to search, then `patients_get` to confirm the record.\n"
            "3) If changes are required, propose an update payload and call `patients_update`.\n"
            "4) Summarize what you changed and what remains pending.\n\n"
            f"User request / symptoms: {symptoms_or_request}\n"
        )

    @mcp.prompt(name="ferreromed_create_order_from_notes")
    def create_order_from_notes(notes: str) -> str:
        """Turn free-text notes into an order creation plan and payload skeleton."""
        return (
            "You are preparing to create an order in FerreroMed.\n\n"
            "Extract from the notes: patient identifiers, delivery address, desired items, dates, and any auth code.\n"
            "Then produce:\n"
            "- a short clarification question list (only what is needed)\n"
            "- a JSON payload skeleton suitable for `orders_create`\n\n"
            f"Notes: {notes}\n"
        )

    @mcp.prompt(name="ferreromed_quotation_decision")
    def quotation_decision(quotation_id: str, decision: str, rationale: str) -> str:
        """Prepare an accept/reject action for a quotation with an auditable rationale."""
        return (
            "You are processing a FerreroMed quotation decision.\n\n"
            "1) Fetch the quotation via `quotations_get`.\n"
            "2) Confirm the decision is one of: accept, reject.\n"
            "3) Call the appropriate tool: `quotations_accept` or `quotations_reject`, using an operator username in `user_upd`.\n"
            "4) Summarize the outcome.\n\n"
            f"quotation_id: {quotation_id}\n"
            f"decision: {decision}\n"
            f"rationale: {rationale}\n"
        )

    @mcp.prompt(name="ferreromed_asl_lookup_helper")
    def asl_lookup_helper(query: str) -> str:
        """Guide an operator to find the right ASL (code + business_entity) from partial info."""
        return (
            "You are an assistant using the FerreroMed MCP tools to find the correct ASL (Account / Service Location).\n\n"
            "Goal: identify the best ASL code and its business_entity for downstream actions (quotations, trips, etc.).\n\n"
            "Steps:\n"
            "1) Ask 1-3 targeted clarification questions only if needed (e.g., business entity, city, known code prefix).\n"
            "2) Use `asls_list` with `asl_code` and/or `business_entity` filters.\n"
            "3) If the result set is large, re-run with a smaller `max_rows` and narrower filters.\n"
            "4) Return: the chosen ASL code(s), a short reason, and the exact filters used.\n\n"
            f"User query: {query}\n"
        )

    @mcp.prompt(name="ferreromed_asl_business_summary")
    def asl_business_summary(asl_code: str | None = None, business_entity: str | None = None) -> str:
        """Summarize ASL distribution by business entity."""
        return (
            "You are analyzing FerreroMed ASLs.\n\n"
            "1) Call `asls_business_counts` using the provided filters (asl_code, business_entity).\n"
            "2) Report: total ASLs (sum of counts), top 5 business entities, and any 'Unknown' bucket if present.\n"
            "3) If counts look suspicious (e.g., zero results), suggest which filter to relax.\n\n"
            f"asl_code filter: {asl_code}\n"
            f"business_entity filter: {business_entity}\n"
        )

    @mcp.prompt(name="ferreromed_asl_data_quality_check")
    def asl_data_quality_check(sample_size: str = "200") -> str:
        """Perform a lightweight quality scan over ASLs using a bounded sample."""
        return (
            "You are doing a quick data-quality check on FerreroMed ASLs.\n\n"
            "1) Call `asls_list` with `max_rows` set to the provided sample size.\n"
            "2) Inspect the rows for common issues:\n"
            "   - missing/blank `name`\n"
            "   - missing/blank `business_entity`\n"
            "   - duplicate `id` values\n"
            "3) Summarize findings with counts and 3-5 concrete examples.\n\n"
            f"sample_size (max_rows): {sample_size}\n"
        )

    @mcp.prompt(name="ferreromed_maps_gather_and_map")
    def maps_gather_and_map(task: str) -> str:
        """Guide an assistant to gather location data from any source and render a map."""
        return (
            "You are an assistant using the FerreroMed MCP tools to build an interactive map.\n\n"
            "Goal: gather locations from *any* source (FerreroMed tools like patients/trips/inventory, user-provided lists, or external sources) "
            "and then render them with `maps_show_custom_locations`.\n\n"
            "Workflow:\n"
            "1) Clarify the mapping intent:\n"
            "   - What are we mapping? (warehouses, pharmacies, patients, delivery points, etc.)\n"
            "   - Do we need NEAREST results? If yes, get an origin (known place like 'Pescara' or 'lat,lng').\n"
            "   - How many results? (limit / nearest_k)\n\n"
            "2) Gather the raw entities:\n"
            "   - Use FerreroMed tools when possible (e.g. `patients_list`, `trips_list`, `inventory_list`).\n"
            "   - If the source is not in FerreroMed, ask the user for a list or fetch via the client’s browsing capabilities (if available).\n\n"
            "3) Normalize into mappable rows. Each row should be a dict with at least:\n"
            "   - name: string\n"
            "   - lat: number\n"
            "   - lng: number\n"
            "   Optional: id, city, address, kind, source\n\n"
            "   If you only have city names (no coordinates), you can approximate using `maps_resolve_known_places` or `maps_list_known_places`.\n"
            "   If you cannot obtain coordinates, say so and ask for them—mapping requires lat/lng.\n\n"
            "4) Render the result:\n"
            "   - Call `maps_show_custom_locations(locations=[...], mode='all'|'nearest', origin=..., nearest_k=..., max_km=..., zoom=..., title=...)`.\n\n"
            "Example locations payload:\n"
            "[\n"
            "  {\"id\": \"WH-001\", \"name\": \"Warehouse Pescara\", \"city\": \"Pescara\", \"lat\": 42.4618, \"lng\": 14.2161, \"kind\": \"warehouse\"},\n"
            "  {\"id\": \"PH-123\", \"name\": \"Farmacia Centro\", \"city\": \"Chieti\", \"lat\": 42.3487, \"lng\": 14.1675, \"kind\": \"pharmacy\"}\n"
            "]\n\n"
            f"Task: {task}\n"
        )
