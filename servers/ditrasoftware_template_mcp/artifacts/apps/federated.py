"""Federated app registrations.

This module is reserved for app providers coming from remote MCP integrations.
"""

from __future__ import annotations

from typing import Any


def create_federated_app_providers(**kwargs) -> tuple[list[Any], dict[str, Any]]:
    """Create remote/federated app providers."""
    return [], {"names": []}
