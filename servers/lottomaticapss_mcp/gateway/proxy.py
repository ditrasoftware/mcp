from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from contextlib import asynccontextmanager

from fastmcp import Client, FastMCP
from mcp.client import advertise
from fastmcp.server.providers.proxy import FastMCPProxy

from ..settings import GatewaySettings, RemoteBackendSettings
from .remote_auth import remote_client_auth
from .connections import current_connection, session_partition


logger = logging.getLogger(__name__)
_RETAINED_CLIENTS: dict[str, Client] = {}
_RETAINED_CLIENT_LOCKS: dict[str, asyncio.Lock] = {}
_MAX_RETAINED_CLIENTS = 128
_RETAINED_IDLE_SECONDS = 900


class RetainedClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active_contexts = 0
        self.last_used = time.monotonic()
        self.retired = False

    async def __aenter__(self):
        if self.retired:
            raise RuntimeError("Analytics session expired; reconstruct the query before rendering again")
        self.active_contexts += 1
        self.last_used = time.monotonic()
        try:
            return await super().__aenter__()
        except BaseException:
            self.active_contexts -= 1
            raise

    async def __aexit__(self, *args):
        try:
            return await super().__aexit__(*args)
        finally:
            self.active_contexts -= 1
            self.last_used = time.monotonic()


async def _evict_idle_clients():
    for key, client in list(_RETAINED_CLIENTS.items()):
        if client.active_contexts != 1 or time.monotonic() - client.last_used < _RETAINED_IDLE_SECONDS:
            continue
        client.retired = True
        _RETAINED_CLIENTS.pop(key, None)
        await client.__aexit__(None, None, None)


async def close_retained_clients():
    clients = list(_RETAINED_CLIENTS.values())
    _RETAINED_CLIENTS.clear()
    for client in clients:
        client.retired = True
    results = await asyncio.gather(*(client.__aexit__(None, None, None) for client in clients), return_exceptions=True)
    _RETAINED_CLIENT_LOCKS.clear()
    if any(isinstance(result, BaseException) for result in results):
        logger.warning("Some downstream sessions failed to close during shutdown")


@asynccontextmanager
async def retained_client_lifespan(server):
    async def reap():
        while True:
            await asyncio.sleep(60)
            async with _RETAINED_CLIENT_LOCKS.setdefault("pool", asyncio.Lock()):
                await _evict_idle_clients()
    reaper = asyncio.create_task(reap())
    try:
        yield
    finally:
        reaper.cancel()
        await asyncio.gather(reaper, return_exceptions=True)
        await close_retained_clients()


def _remote_client_key(remote_name: str, remote_url: str) -> str:
    connection = current_connection(remote_name)
    connection_id = connection.id if connection is not None else "legacy"
    return f"{remote_name}|{remote_url}|{connection_id}|{session_partition()}"


async def _retained_client_factory(
    *,
    remote: RemoteBackendSettings,
    timeout_seconds: float,
    advertise_mcp_apps_ui: bool,
) -> Client:
    """Return a bounded, idle-expiring downstream client for the current identity.

    Metabase query handles are associated with an MCP session. FastMCP's default
    proxy factory creates a new downstream client per call, which loses handles
    between construct_query and visualize_query. Keep one base client entered;
    proxy calls enter it reentrantly and leave the base connection alive.
    """
    key = _remote_client_key(remote.name, remote.url)
    lock = _RETAINED_CLIENT_LOCKS.setdefault("pool", asyncio.Lock())
    async with lock:
        await _evict_idle_clients()
        existing = _RETAINED_CLIENTS.get(key)
        if existing is not None and existing.is_connected():
            existing.last_used = time.monotonic()
            return existing
        if existing is not None:
            existing.retired = True
            _RETAINED_CLIENTS.pop(key, None)
            await existing.__aexit__(None, None, None)
        if len(_RETAINED_CLIENTS) >= _MAX_RETAINED_CLIENTS:
            raise RuntimeError("Downstream session capacity reached; retry after an idle session expires")

        client_kwargs: dict[str, object] = {"timeout": timeout_seconds}
        if remote.name == "ditra-analytics":
            client_kwargs["mode"] = "legacy"
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
        client = RetainedClient(remote.url, **client_kwargs)
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
