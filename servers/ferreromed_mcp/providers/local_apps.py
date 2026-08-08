from __future__ import annotations

from typing import Any

from ..apps.ferreromed_app import create_ferreromed_app
from ..rest_client import FerreroMedRestClient
from ..settings import FerreroMedSettings


def create_local_app_providers(
    client: FerreroMedRestClient,
    settings: FerreroMedSettings,
) -> tuple[list[Any], dict[str, Any]]:
    """Create local app providers and return provider metadata."""

    app_provider = create_ferreromed_app(client, settings)
    return [app_provider], {"names": ["FerreroMed"]}
