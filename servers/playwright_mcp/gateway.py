from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server import create_proxy


def mount_native_playwright(mcp: FastMCP, *, url: str | None, namespace: str) -> bool:
    """Mount the original Playwright MCP so tools, resources, and prompts stay native."""
    if not url:
        return False
    native = create_proxy(url, name="Native Playwright MCP")
    mcp.mount(native, namespace=namespace)
    return True