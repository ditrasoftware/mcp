from __future__ import annotations

from dataclasses import dataclass
import inspect

from fastmcp import FastMCP
from fastmcp.server import create_proxy

from ..settings import GatewaySettings
from .remote_auth import resolve_remote_auth_sync


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

    try:
        create_proxy_params = inspect.signature(create_proxy).parameters
    except Exception:
        create_proxy_params = {}
    supports_auth = "auth" in create_proxy_params

    for remote in gateway.remotes:
        if remote.type != "streamable-http":
            # Keep v1 strict and explicit: this implementation targets HTTP remotes.
            continue

        kwargs: dict[str, object] = {"name": remote.name}
        if supports_auth:
            auth = resolve_remote_auth_sync(remote)
            if auth:
                kwargs["auth"] = auth

        proxy = create_proxy(remote.url, **kwargs)
        mcp.mount(proxy, namespace=remote.namespace)
        mounted.append(MountedRemote(name=remote.name, namespace=remote.namespace, url=remote.url))

    return mounted
