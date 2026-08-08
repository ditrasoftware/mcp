from __future__ import annotations

from fastmcp import FastMCP

from ..rest_client import FerreroMedAuth, FerreroMedRestClient


def register_resources(mcp: FastMCP, client: FerreroMedRestClient) -> None:
    @mcp.resource("ferreromed://openapi.yaml")
    async def openapi_yaml() -> str:
        """OpenAPI schema for the underlying FerreroMed REST API (YAML)."""
        # Auth is not required for /openapi.yaml in the REST server.
        return await client.request("GET", "/openapi.yaml", expect_json=False)

    @mcp.resource("ferreromed://health")
    async def health() -> str:
        """Health status for the underlying FerreroMed REST API."""
        data = await client.request("GET", "/health")
        return str(data)
