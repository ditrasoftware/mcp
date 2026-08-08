from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..resources.openapi import register_resources
from ..rest_client import FerreroMedRestClient


def register_local_resources(mcp: FastMCP, client: FerreroMedRestClient) -> dict[str, Any]:
    """Register local resources and return resource metadata."""

    register_resources(mcp, client)
    return {
        "uris": [
            "ferreromed://openapi.yaml",
            "ferreromed://health",
        ]
    }
