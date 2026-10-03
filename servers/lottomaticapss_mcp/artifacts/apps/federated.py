"""Federated app registrations.

Reserved for remote/adapter-backed Prefab apps.
"""

from __future__ import annotations

from typing import Any


def create_federated_app_providers(*args: Any, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
    """Create remote/federated app providers."""
    return [], {}
