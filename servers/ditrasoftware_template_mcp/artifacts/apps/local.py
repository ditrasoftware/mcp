"""Template for custom applications.

TODO: Customize or replace with your own apps.

FastMCP 4.0.x patterns:
- 90% of apps use PrefabApp (auto-synthesized UI from tool schemas)
- Only create custom apps for complex workflows or special visualizations
"""

from __future__ import annotations

from typing import Any

from fastmcp.app import PrefabApp

from ...rest_client import DitraSoftwareRestClient
from ...settings import DitraSoftwareSettings


def create_local_app_providers(
    client: DitraSoftwareRestClient,
    settings: DitraSoftwareSettings,
) -> tuple[list[Any], dict[str, Any]]:
    """Create your custom applications.
    
    TODO: Replace with your actual apps.
    
    FastMCP 4.0.x guideline:
    - Start with PrefabApp (auto-synthesized from tool schemas)
    - Only add custom logic for complex workflows
    """
    
    app_providers: list[Any] = []
    local_app_registry: dict[str, Any] = {"names": []}
    
    # EXAMPLE: Auto-synthesized app from your tools
    # Most apps only need this - FastMCP 4.0.x generates UI automatically
    
    example_app = PrefabApp(
        name="example_dashboard",
        title="Example Dashboard",
        description="TODO: Update with your dashboard description",
        tools=[
            "hello_world",              # TODO: Replace with your tools
            "get_tenant_context",
        ],
        resources=[
            "yourorg://health",         # TODO: Replace with your resources
            "yourorg://config",
        ],
    )
    
    app_providers.append(example_app)
    local_app_registry["names"].append("example_dashboard")
    
    # TODO: Add more PrefabApp instances for other workflows
    # 
    # your_workflow_app = PrefabApp(
    #     name="your_workflow",
    #     title="Your Workflow",
    #     description="Description of workflow",
    #     tools=[
    #         "your_tool_1",
    #         "your_tool_2",
    #     ],
    #     resources=[
    #         "yourorg://resource_1",
    #     ],
    # )
    # 
    # apps.append(your_workflow_app)
    
    return app_providers, local_app_registry
