from __future__ import annotations

import json
import time
from typing import Any

from fastmcp import Client

from ..settings import GatewaySettings, RemoteBackendSettings
from .remote_auth import (
    GatewayAuthConfigurationError,
    is_refresh_flow_configured,
    resolve_remote_auth,
    resolve_remote_auth_force_refresh,
)


def _dump_content_block(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block

    if hasattr(block, "model_dump"):
        try:
            dumped = block.model_dump(mode="json")
        except Exception:
            dumped = block.model_dump()
        if isinstance(dumped, dict):
            return dumped

    block_type = getattr(block, "type", None)
    if block_type == "text":
        return {"type": "text", "text": str(getattr(block, "text", ""))}

    # Last-resort fallback keeps output visible instead of dropping it.
    return {"type": "text", "text": str(block)}


def _normalize_call_tool_result(result: Any) -> dict[str, Any] | None:
    """Convert FastMCP client tool results to MCP-compatible dicts without losing content."""

    content_blocks: list[dict[str, Any]] = []
    raw_content = getattr(result, "content", None)
    if isinstance(raw_content, list):
        content_blocks = [_dump_content_block(block) for block in raw_content]

    is_error = getattr(result, "isError", None)
    if is_error is None:
        is_error = getattr(result, "is_error", False)

    structured_content = getattr(result, "structuredContent", None)
    if structured_content is None:
        structured_content = getattr(result, "structured_content", None)

    # If content is unexpectedly empty but the client exposes parsed data,
    # render it as a text block so callers still receive visible output.
    if not content_blocks and hasattr(result, "data"):
        data = getattr(result, "data")
        if data is not None:
            if isinstance(data, str):
                text = data
            else:
                try:
                    text = json.dumps(data, ensure_ascii=False, default=str)
                except Exception:
                    text = str(data)
            content_blocks = [{"type": "text", "text": text}]

    if content_blocks or structured_content is not None or hasattr(result, "isError") or hasattr(result, "is_error"):
        normalized: dict[str, Any] = {
            "content": content_blocks,
            "isError": bool(is_error),
        }
        if structured_content is not None:
            normalized["structuredContent"] = structured_content
        return normalized

    return None


def get_remote_backend(
    gateway: GatewaySettings,
    *,
    remote_name: str,
) -> RemoteBackendSettings | None:
    return next((r for r in gateway.remotes if r.name == remote_name), None)


def list_remote_tool_names(gateway: GatewaySettings) -> list[str]:
    names: list[str] = []
    for remote in gateway.remotes:
        names.append(remote.name)
    return names


def _looks_like_auth_failure(exc: Exception) -> bool:
    text = str(exc).lower()
    hints = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "invalid_token",
        "insufficient_scope",
        "www-authenticate",
        "bearer",
    )
    return any(h in text for h in hints)


def _raise_auth_diagnostic(remote: RemoteBackendSettings, *, action: str, exc: Exception) -> None:
    text = str(exc)
    lowered = text.lower()

    if "insufficient_scope" in lowered or "scope" in lowered:
        raise RuntimeError(
            f"Remote auth failed during {action} for {remote.name}: insufficient OAuth scope. "
            "Update remote scope configuration and refresh credentials before retrying. Original error: "
            f"{text}"
        ) from exc

    if _looks_like_auth_failure(exc):
        raise RuntimeError(
            f"Remote auth failed during {action} for {remote.name}: token rejected or expired. "
            "Check remote bearer-token or refresh-token settings, then refresh token. "
            f"Original error: {text}"
        ) from exc

    raise RuntimeError(f"Remote call failed during {action} for {remote.name}: {text}") from exc


async def _call_with_client(
    remote: RemoteBackendSettings,
    *,
    auth: str | None,
    operation: Any,
) -> Any:
    client_kwargs: dict[str, Any] = {
        "timeout": max(remote.timeout_ms / 1000.0, 1.0),
    }
    if auth:
        client_kwargs["auth"] = auth

    async with Client(remote.url, **client_kwargs) as client:
        return await operation(client)


async def _execute_remote_operation(
    remote: RemoteBackendSettings,
    *,
    action: str,
    operation: Any,
) -> Any:
    try:
        auth = await resolve_remote_auth(remote)
    except GatewayAuthConfigurationError as exc:
        raise RuntimeError(f"Remote auth configuration error for {remote.name}: {exc}") from exc

    try:
        return await _call_with_client(remote, auth=auth, operation=operation)
    except Exception as exc:
        can_retry = _looks_like_auth_failure(exc) and is_refresh_flow_configured(remote)
        if can_retry:
            try:
                refreshed_auth = await resolve_remote_auth_force_refresh(remote)
                return await _call_with_client(remote, auth=refreshed_auth, operation=operation)
            except Exception as retry_exc:
                _raise_auth_diagnostic(remote, action=action, exc=retry_exc)

        _raise_auth_diagnostic(remote, action=action, exc=exc)


async def list_remote_tools(
    gateway: GatewaySettings,
    *,
    remote_name: str,
) -> list[str]:
    """Best-effort tool names from a configured remote backend."""

    remote = get_remote_backend(gateway, remote_name=remote_name)
    if remote is None:
        raise ValueError(f"Unknown remote backend: {remote_name}")
    if remote.type != "streamable-http":
        raise ValueError(f"Unsupported remote type for listing tools: {remote.type}")

    async def _op(client: Client) -> list[Any]:
        list_tools = getattr(client, "list_tools", None)
        if not callable(list_tools):
            return []
        return await list_tools()

    tools = await _execute_remote_operation(
        remote,
        action="list_tools",
        operation=_op,
    )

    names: list[str] = []
    for tool in tools or []:
        name = getattr(tool, "name", None)
        if isinstance(name, str) and name:
            names.append(name)
    return names


async def probe_remote_backend(
    gateway: GatewaySettings,
    *,
    remote_name: str,
) -> dict[str, Any]:
    """Probe connectivity and optional tool listing for one remote backend."""

    remote = get_remote_backend(gateway, remote_name=remote_name)
    if remote is None:
        raise ValueError(f"Unknown remote backend: {remote_name}")
    if remote.type != "streamable-http":
        raise ValueError(f"Unsupported remote type for health probe: {remote.type}")

    started = time.perf_counter()
    tool_names: list[str] = []
    supports_list_tools = False
    async def _op(client: Client) -> list[Any]:
        nonlocal supports_list_tools
        list_tools = getattr(client, "list_tools", None)
        if not callable(list_tools):
            return []
        supports_list_tools = True
        return await list_tools()

    tools = await _execute_remote_operation(
        remote,
        action="health_probe",
        operation=_op,
    )
    for tool in tools or []:
        name = getattr(tool, "name", None)
        if isinstance(name, str) and name:
            tool_names.append(name)
    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "name": remote.name,
        "namespace": remote.namespace,
        "type": remote.type,
        "url": remote.url,
        "healthy": True,
        "latency_ms": latency_ms,
        "supports_list_tools": supports_list_tools,
        "tool_count": len(tool_names),
        "sample_tools": tool_names[:25],
    }


async def call_remote_tool_direct(
    gateway: GatewaySettings,
    *,
    remote_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    result_strategy: str | None = None,
) -> Any:
    """Call a tool on a configured remote MCP server via FastMCP Client."""

    remote = get_remote_backend(gateway, remote_name=remote_name)
    if remote is None:
        raise ValueError(f"Unknown remote backend: {remote_name}")

    if remote.type != "streamable-http":
        raise ValueError(f"Unsupported remote type for direct call: {remote.type}")

    async def _op(client: Client) -> Any:
        return await client.call_tool(tool_name, arguments or {})

    result = await _execute_remote_operation(
        remote,
        action=f"call_tool:{tool_name}",
        operation=_op,
    )

    # Default behavior is true pass-through fidelity so downstream MCP semantics
    # remain intact unless wrapper behavior is explicitly requested.
    strategy = (result_strategy or gateway.direct_result_strategy or "passthrough").strip().lower()
    if strategy not in {"passthrough", "normalized"}:
        strategy = "passthrough"
    if strategy == "passthrough":
        return result

    normalized = _normalize_call_tool_result(result)
    if normalized is not None:
        return normalized

    if hasattr(result, "model_dump"):
        try:
            return result.model_dump(mode="json")
        except Exception:
            return result.model_dump()

    if hasattr(result, "data"):
        return getattr(result, "data")

    return result
