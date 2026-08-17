from __future__ import annotations

from typing import Any

from ..apps.anticafarmacia_app import create_anticafarmacia_app
from ..rest_client import DitraSoftwareRestClient
from ..settings import DitraSoftwareSettings


def create_local_app_providers(
    client: DitraSoftwareRestClient,
    settings: DitraSoftwareSettings,
) -> tuple[list[Any], dict[str, Any]]:
    """Create local Prefab UI providers."""

    app_provider = create_anticafarmacia_app(client, settings)
    return [app_provider], {"names": ["AnticaFarmacia"]}
