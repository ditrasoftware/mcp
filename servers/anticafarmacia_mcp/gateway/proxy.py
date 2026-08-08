from __future__ import annotations

from dataclasses import dataclass

from fastmcp import FastMCP
from fastmcp.server import create_proxy

from ..settings import GatewaySettings


@dataclass(frozen=True)
class MountedRemote:
    name: str
    namespace: str
    url: str


def mount_remote_proxies(mcp: FastMCP, gateway: GatewaySettings) -> list[MountedRemote]:
    """Mount enabled remote MCP servers as namespaced proxy providers."""

    mounted: list[MountedRemote] = []
    if not gateway.mount_on_startup:
        return mounted

    for remote in gateway.remotes:
        if remote.type != "streamable-http":
            # Keep v1 strict and explicit: this implementation targets HTTP remotes.
            continue

        proxy = create_proxy(remote.url, name=remote.name)
        mcp.mount(proxy, namespace=remote.namespace)
        mounted.append(MountedRemote(name=remote.name, namespace=remote.namespace, url=remote.url))

    return mounted
