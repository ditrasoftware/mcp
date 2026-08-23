"""Enterprise applications demonstrating FastMCP 4.0.x patterns.

Apps show:
- PrefabApp for auto-synthesized UIs (90% of apps)
- Simple container UIs for workflow composition
- Custom app logic only for complex workflows
"""

from __future__ import annotations

from typing import Any

from fastmcp.app import PrefabApp

from ...rest_client import DitraDevtestRestClient
from ...settings import DitraDevtestSettings


def create_local_app_providers(
    client: DitraDevtestRestClient,
    settings: DitraDevtestSettings,
) -> tuple[list[Any], dict[str, Any]]:
    """Create enterprise applications.
    
    These demonstrate FastMCP 4.0.x app patterns:
    - 90% auto-synthesized from tool schemas
    - Only custom when workflow or visualization needed
    """
    
    app_providers: list[Any] = []
    local_app_registry: dict[str, Any] = {"names": []}
    
    # APP 1: Auto-synthesized diagnostics dashboard
    # FastMCP 4.0.x automatically generates UI from tool schema
    diagnostics_app = PrefabApp(
        name="diagnostics",
        title="Enterprise Diagnostics Dashboard",
        description="View system health, capabilities, and configuration",
        tools=[
            "local_auth_debug",           # Auto-UI for checking tenant/auth
            "local_gateway_summary",      # Auto-UI for capability overview
            "local_error_taxonomy_lookup", # Auto-UI for error search
            "local_capability_inspect",   # Auto-UI for detailed contracts
        ],
        resources=[
            "ditra://health",
            "ditra://gateway/remotes",
            "ditra://capability-registry",
            "ditra://error-taxonomy",
        ],
    )
    
    app_providers.append(diagnostics_app)
    local_app_registry["names"].append("diagnostics")
    
    # APP 2: Auto-synthesized patient management workflow
    patient_mgmt_app = PrefabApp(
        name="patient_management",
        title="Patient Management",
        description="Search for patients and create orders",
        tools=[
            "local_sample_patient_search",  # Auto-UI form for search
            "local_sample_order_create",     # Auto-UI form for order creation
        ],
        resources=[
            "ditra://sample/patients/{patient_id}",
        ],
    )
    
    app_providers.append(patient_mgmt_app)
    local_app_registry["names"].append("patient_management")
    
    # APP 3: Custom container layout (if you need more control than auto-synthesis)
    # In most cases, use PrefabApp instead
    
    # This example shows a conceptual multi-panel workflow layout
    # (You would only do this if PrefabApp's auto-synthesis wasn't sufficient)
    
    # workflow_container = AppContainer(
    #     direction=ContainerDirection.VERTICAL,
    #     children=[
    #         # Left panel: search results
    #         {
    #             "type": "tool_form",
    #             "tool": "local_sample_patient_search",
    #             "flex": 1,
    #         },
    #         # Right panel: order creation
    #         {
    #             "type": "tool_form", 
    #             "tool": "local_sample_order_create",
    #             "flex": 1,
    #         },
    #     ],
    # )
    
    return app_providers, local_app_registry
