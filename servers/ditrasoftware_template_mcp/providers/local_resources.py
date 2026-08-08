from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..rest_client import DitraSoftwareRestClient
from ..settings import DitraSoftwareSettings


def register_local_resources(
    mcp: FastMCP,
    client: DitraSoftwareRestClient,
) -> dict[str, Any]:
    """Register domain-specific local resources.
    
    TODO: Implement your domain-specific resources here.
    
    Resources can be OpenAPI schemas, reference data, or other
    document-based content that tools may reference.
    """
    
    local_resource_registry: dict[str, Any] = {}
    
    # TODO: Add your domain-specific resources below
    # Example:
    # @mcp.resource("resource://example/schema")
    # async def my_resource() -> str:
    #     \"\"\"My domain-specific resource.\"\"\"
    #     return "resource content"
    #
    # local_resource_registry["my_resource"] = ...
    
    return local_resource_registry
