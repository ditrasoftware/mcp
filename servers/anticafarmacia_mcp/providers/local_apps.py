from __future__ import annotations

from typing import Any

from ..rest_client import DitraSoftwareRestClient
from ..settings import DitraSoftwareSettings


def create_local_app_providers(
    client: DitraSoftwareRestClient,
    settings: DitraSoftwareSettings,
) -> tuple[list[Any], dict[str, Any]]:
    """Create domain-specific Prefab UI apps.
    
    TODO: Implement your domain-specific UI apps here.
    
    Apps provide interactive Prefab UI components that let users
    interact with your tools through a visual console.
    """
    
    app_providers: list[Any] = []
    local_app_registry: dict[str, Any] = {}
    
    # TODO: Add your domain-specific UI apps below
    # Example:
    # class MyApp(AppProvider):
    #     @app.ui()
    #     async def main_ui() -> str:
    #         \"\"\"Main UI for my domain.\"\"\"
    #         return "<html>My App</html>"
    #
    # app_providers.append(MyApp())
    # local_app_registry["my_app"] = ...
    
    return app_providers, local_app_registry
