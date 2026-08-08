from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context

from ..rest_client import DitraSoftwareAuth, DitraSoftwareRestClient
from ..settings import DitraSoftwareSettings


def register_local_tools(
    mcp: FastMCP,
    client: DitraSoftwareRestClient,
    settings: DitraSoftwareSettings,
    *,
    _ctx_or_current: Callable[[Context | None], Context | None],
    _header_auth: Callable[[Context | None], DitraSoftwareAuth],
    _auth_from_args: Callable[..., DitraSoftwareAuth],
    _require_auth: Callable[[DitraSoftwareAuth], None],
    _apply_default_auth: Callable[..., DitraSoftwareAuth],
    _coerce_positive_int: Callable[[int | str | None], int | None],
) -> set[str]:
    """Register domain-specific local tools.
    
    TODO: Implement your domain-specific tools here.
    
    This function should use @mcp.tool() decorators to register tools
    and return the set of registered tool names.
    """
    
    local_tool_names: set[str] = set()
    
    # TODO: Add your domain-specific tools below
    # Example:
    # @mcp.tool()
    # async def my_tool(arg: str) -> str:
    #     \"\"\"My domain-specific tool.\"\"\"
    #     return f"Result: {arg}"
    #
    # local_tool_names.add("my_tool")
    
    return local_tool_names
