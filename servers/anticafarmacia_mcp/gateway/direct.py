from __future__ import annotations

import json
import logging
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
from .resilience import GatewayResilienceManager

logger = logging.getLogger(__name__)


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
            "Update GOOGLE_WORKSPACE_MCP_OAUTH_SCOPE to include required Google scopes, "
            "re-run OAuth bootstrap, then retry. Original error: "
            f"{text}"
        ) from exc

    if _looks_like_auth_failure(exc):
        raise RuntimeError(
            f"Remote auth failed during {action} for {remote.name}: token rejected or expired. "
            "Check GOOGLE_WORKSPACE_MCP_BEARER_TOKEN or refresh-token settings, then refresh token. "
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


async def discover_remote_tools_with_namespaces(
    gateway: GatewaySettings,
) -> dict[str, Any]:
    """Discover all tools on all configured remotes, organized by namespace.

    Returns a dict with:
      - tools_by_remote: {remote_name -> [tool_infos]}
      - namespaced_tools: {full_name -> tool_info}
      - collisions: {base_name -> [remotes_with_collision]}
      - collision_summary: human-readable summary
    """
    from .namespace import RemoteToolNamespace, RemoteToolInfo

    namespace = RemoteToolNamespace(gateway)
    tools_by_remote: dict[str, list[dict[str, Any]]] = {}
    namespaced_tools: dict[str, dict[str, Any]] = {}
    collision_map: dict[str, set[str]] = {}

    for remote in gateway.remotes:
        if not remote.enabled or remote.type != "streamable-http":
            continue

        try:
            tool_names = await list_remote_tools(gateway, remote_name=remote.name)
            tools_list = []
            for tool_name in tool_names:
                tool_info = namespace.build_remote_tool_info(
                    remote.name,
                    tool_name,
                    description=None,
                )
                tools_list.append(
                    {
                        "name": tool_name,
                        "remote": remote.name,
                        "namespace": remote.namespace,
                        "full_name": tool_info.full_name,
                    }
                )

                # Detect collisions
                if tool_name not in collision_map:
                    collision_map[tool_name] = set()
                collision_map[tool_name].add(remote.name)

                # Add to namespace map
                namespaced_tools[tool_info.full_name] = {
                    "name": tool_name,
                    "remote": remote.name,
                    "namespace": remote.namespace,
                    "full_name": tool_info.full_name,
                }

            tools_by_remote[remote.name] = tools_list
            namespace.add_remote_tools(remote.name, [namespace.build_remote_tool_info(remote.name, tn) for tn in tool_names])

        except Exception as exc:
            tools_by_remote[remote.name] = {
                "error": str(exc),
                "tools": [],
            }

    # Build collision info
    collisions = {
        base_name: list(remotes)
        for base_name, remotes in collision_map.items()
        if len(remotes) > 1
    }

    return {
        "tools_by_remote": tools_by_remote,
        "namespaced_tools": namespaced_tools,
        "collisions": collisions,
        "collision_summary": namespace.get_collision_summary(),
        "total_remotes": len([r for r in gateway.remotes if r.enabled]),
        "total_tools": len(namespaced_tools),
        "collision_count": len(collisions),
    }


async def call_remote_tool_by_namespace(
    gateway: GatewaySettings,
    *,
    full_name: str,
    arguments: dict[str, Any] | None = None,
    result_strategy: str | None = None,
) -> Any:
    """Call a remote tool using its full namespaced name.

    Examples:
      - full_name="remote:google-workspace-mcp:list_users"
      - full_name="remote:google-toolbox-mcp:create_task"

    Raises ValueError if:
      - full_name is not in the correct format
      - remote or tool does not exist
    """
    from .namespace import RemoteToolNamespace

    parsed = RemoteToolNamespace.parse_full_name(full_name)
    if parsed is None:
        raise ValueError(
            f"Invalid namespaced tool name format: '{full_name}'. "
            f"Expected: 'remote:<remote_name>:<tool_name>'. "
            f"Example: 'remote:google-workspace-mcp:list_users'"
        )

    remote_name, tool_name = parsed
    return await call_remote_tool_direct(
        gateway,
        remote_name=remote_name,
        tool_name=tool_name,
        arguments=arguments,
        result_strategy=result_strategy,
    )


async def get_remote_tool_suggestions(
    gateway: GatewaySettings,
    *,
    partial_name: str | None = None,
) -> dict[str, Any]:
    """Get tool suggestions for remotes, optionally filtered by partial name.

    Useful for:
      - Discovering available tools across all remotes
      - Finding tools by partial name match
      - Resolving ambiguous tool names

    If partial_name="list", returns all tools containing "list" from any remote.
    """
    all_tools = await discover_remote_tools_with_namespaces(gateway)
    namespaced = all_tools.get("namespaced_tools", {})

    if not partial_name:
        return {
            "suggestions": list(namespaced.keys()),
            "total": len(namespaced),
        }

    partial_lower = partial_name.lower()
    matching = {
        full_name: info
        for full_name, info in namespaced.items()
        if partial_lower in full_name.lower()
    }

    return {
        "query": partial_name,
        "suggestions": list(matching.keys()),
        "total": len(matching),
        "tools": matching,
    }


async def discover_remote_tools_with_resilience(
    gateway: GatewaySettings,
    *,
    resilience_mgr: GatewayResilienceManager | None = None,
) -> dict[str, Any]:
    """Discover all tools on all remotes with per-remote timeout and error isolation.

    Each remote's tool listing happens in parallel with a per-remote timeout (default: 10s).
    If one remote times out or fails, other remotes are unaffected (error isolation).
    Local tools availability is guaranteed.

    Returns:
      - tools_by_remote: {remote_name -> [tool_list or error dict]}
      - namespaced_tools: {full_name -> tool_info}
      - remote_health: {remote_name -> RemoteHealthStatus}
      - collisions: {tool_name -> [remotes_with_collision]}
      - collision_summary: human-readable warning
      - total_remotes: count of enabled remotes
      - total_tools: count of unique tools across all remotes
      - collision_count: number of collision groups
    """
    if resilience_mgr is None:
        resilience_mgr = GatewayResilienceManager()

    # Register all remotes
    for remote in gateway.remotes:
        resilience_mgr.register_remote(remote.name, remote.namespace, enabled=remote.enabled)

    # Discover tools from all remotes in parallel with error isolation
    remote_tools_by_name: dict[str, list[str]] = {}
    tools_by_remote: dict[str, Any] = {}
    all_tools: dict[str, dict[str, Any]] = {}
    collision_map: dict[str, set[str]] = {}

    # Create tasks for each remote
    tasks: list[tuple[str, Any]] = []
    for remote in gateway.remotes:
        if not remote.enabled:
            tools_by_remote[remote.name] = {"error": "disabled", "tools": []}
            continue

        async def _discover_one_remote(remote_name: str = remote.name) -> list[str]:
            return await list_remote_tools(gateway, remote_name=remote_name)

        tasks.append((remote.name, _discover_one_remote))

    # Execute with resilience isolation
    results = await resilience_mgr.call_all_remotes_with_isolation(
        tasks,
        operation_name="discover_remote_tools",
        timeout_ms=resilience_mgr.list_tools_timeout_ms,
    )

    # Process results
    for remote_name, tool_names in results.items():
        health = resilience_mgr.get_health_status(remote_name)

        if tool_names is None:
            # Remote failed; include error info
            tools_by_remote[remote_name] = {
                "error": health.error if health else "unknown error",
                "tools": [],
            }
        else:
            # Remote succeeded
            tool_list = []
            for tool_name in tool_names:
                tool_info = {
                    "name": tool_name,
                    "remote": remote_name,
                    "full_name": f"remote:{remote_name}:{tool_name}",
                }
                tool_list.append(tool_info)

                # Track for namespacing
                all_tools[tool_info["full_name"]] = tool_info

                # Track collisions
                if tool_name not in collision_map:
                    collision_map[tool_name] = set()
                collision_map[tool_name].add(remote_name)

            tools_by_remote[remote_name] = {"tools": tool_list}

    # Build collision info
    collisions = {
        base_name: list(remotes)
        for base_name, remotes in collision_map.items()
        if len(remotes) > 1
    }

    # Build collision summary
    collision_summary_lines = []
    if collisions:
        collision_summary_lines.append(f"Tool name collisions detected ({len(collisions)} total):")
        for tool_name in sorted(collisions.keys()):
            remotes = sorted(collisions[tool_name])
            collision_summary_lines.append(f"  • '{tool_name}' found in: {', '.join(remotes)}")
        collision_summary_lines.append("\nUse full names to disambiguate:")
        for tool_name in sorted(collisions.keys()):
            for remote_name in sorted(collisions[tool_name]):
                full = f"remote:{remote_name}:{tool_name}"
                collision_summary_lines.append(f"  • {full}")
    else:
        collision_summary_lines.append("No tool name collisions detected.")

    return {
        "tools_by_remote": tools_by_remote,
        "namespaced_tools": all_tools,
        "collisions": collisions,
        "collision_summary": "\n".join(collision_summary_lines),
        "remote_health": {name: health.__dict__ for name, health in resilience_mgr.get_all_health_status().items()},
        "total_remotes": len([r for r in gateway.remotes if r.enabled]),
        "total_tools": len(all_tools),
        "collision_count": len(collisions),
    }


async def call_remote_tool_with_resilience(
    gateway: GatewaySettings,
    *,
    remote_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    result_strategy: str | None = None,
    resilience_mgr: GatewayResilienceManager | None = None,
) -> Any:
    """Call a remote tool with per-remote timeout and error isolation.

    Timeout: default 30s per-remote (configurable).
    On error (timeout, auth failure, network failure), the error is logged but
    not raised; instead, a clear error dict is returned with context.

    Args:
      - remote_name, tool_name, arguments, result_strategy: same as call_remote_tool_direct()
      - resilience_mgr: optional GatewayResilienceManager; created if not provided

    Returns:
      - Tool result on success
      - Error dict on failure: {"error": str, "remote": str, "tool": str, "timeout_s": float}

    Example:
      result = await call_remote_tool_with_resilience(
          gateway,
          remote_name="google-workspace-mcp",
          tool_name="list_users",
          arguments={"max_results": 10}
      )
    """
    if resilience_mgr is None:
        resilience_mgr = GatewayResilienceManager()

    remote = get_remote_backend(gateway, remote_name=remote_name)
    if remote is None:
        return {
            "error": f"Unknown remote backend: {remote_name}",
            "remote": remote_name,
            "tool": tool_name,
        }

    resilience_mgr.register_remote(remote.name, remote.namespace, enabled=remote.enabled)

    async def _call_tool() -> Any:
        return await call_remote_tool_direct(
            gateway,
            remote_name=remote_name,
            tool_name=tool_name,
            arguments=arguments,
            result_strategy=result_strategy,
        )

    result = await resilience_mgr.call_with_timeout_and_isolation(
        remote_name,
        operation=_call_tool,
        operation_name=f"call_tool:{tool_name}",
        timeout_ms=resilience_mgr.call_tool_timeout_ms,
    )

    if result is None:
        # Operation failed or timed out; return error dict with context
        health = resilience_mgr.get_health_status(remote_name)
        return {
            "error": health.error if health else "Unknown error",
            "remote": remote_name,
            "tool": tool_name,
            "timeout_s": resilience_mgr.call_tool_timeout_ms / 1000.0,
            "reachable": health.reachable if health else False,
        }

    return result
