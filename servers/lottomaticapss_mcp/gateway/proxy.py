from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from fastmcp import Client, FastMCP
from mcp.client import advertise
from fastmcp.server.providers.proxy import FastMCPProxy

from ..settings import GatewaySettings, RemoteBackendSettings
from .remote_auth import remote_client_auth


logger = logging.getLogger(__name__)
_RETAINED_CLIENTS: dict[str, Client] = {}
_RETAINED_CLIENT_LOCKS: dict[str, asyncio.Lock] = {}


def _remote_client_key(remote_name: str, remote_url: str) -> str:
    return f"{remote_name}|{remote_url}"


async def _retained_client_factory(
    *,
    remote: RemoteBackendSettings,
    timeout_seconds: float,
    advertise_mcp_apps_ui: bool,
) -> Client:
    """Return a live downstream client retained for the server process lifetime.

    Metabase query handles are associated with an MCP session. FastMCP's default
    proxy factory creates a new downstream client per call, which loses handles
    between construct_query and visualize_query. Keep one base client entered;
    proxy calls enter it reentrantly and leave the base connection alive.
    """
    key = _remote_client_key(remote.name, remote.url)
    lock = _RETAINED_CLIENT_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        existing = _RETAINED_CLIENTS.get(key)
        if existing is not None and existing.is_connected():
            return existing

        client_kwargs: dict[str, object] = {"timeout": timeout_seconds}
        auth = remote_client_auth(remote)
        if auth is not None:
            client_kwargs["auth"] = auth
        if advertise_mcp_apps_ui:
            client_kwargs["extensions"] = [
                advertise(
                    "io.modelcontextprotocol/ui",
                    {"mimeTypes": ["text/html;profile=mcp-app"]},
                )
            ]
        client = Client(remote.url, **client_kwargs)
        await client.__aenter__()
        _RETAINED_CLIENTS[key] = client
        return client


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

        kwargs: dict[str, object] = {"name": remote.name}

        async def client_factory(
            remote: RemoteBackendSettings = remote,
            timeout_seconds: float = max(remote.timeout_ms / 1000.0, 1.0),
            advertise_mcp_apps_ui: bool = gateway.advertise_mcp_apps_ui,
        ) -> Client:
            return await _retained_client_factory(
                remote=remote,
                timeout_seconds=timeout_seconds,
                advertise_mcp_apps_ui=advertise_mcp_apps_ui,
            )

        proxy = FastMCPProxy(client_factory=client_factory, **kwargs)
        mcp.mount(proxy, namespace=remote.namespace)
        mounted.append(MountedRemote(name=remote.name, namespace=remote.namespace, url=remote.url))

    return mounted
