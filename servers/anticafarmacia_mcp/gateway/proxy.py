from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging

from fastmcp import FastMCP
from fastmcp.server import create_proxy

from ..settings import GatewaySettings
from .remote_auth import resolve_remote_auth_sync

logger = logging.getLogger(__name__)


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
            try:
                auth = resolve_remote_auth_sync(remote)
                if auth:
                    kwargs["auth"] = auth
            except Exception as exc:
                # Degrade gracefully at startup; auth can still be resolved on-demand by direct calls.
                logger.warning(
                    "Remote auth warmup failed for %s (%s); mounting proxy without auth. error=%s",
                    remote.name,
                    remote.namespace,
                    exc,
                )

        try:
            proxy = create_proxy(remote.url, **kwargs)
            mcp.mount(proxy, namespace=remote.namespace)
            mounted.append(MountedRemote(name=remote.name, namespace=remote.namespace, url=remote.url))
        except Exception as exc:
            # A broken remote should not block local MCP startup.
            logger.error(
                "Failed to mount remote proxy %s (%s) at %s: %s",
                remote.name,
                remote.namespace,
                remote.url,
                exc,
            )
            continue

    return mounted
