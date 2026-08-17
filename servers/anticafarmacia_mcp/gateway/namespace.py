"""
Namespace management for remote MCP tools.

Provides collision-free tool naming across multiple remote MCP backends.

Key patterns:
  - Global namespace: `remote:<remote_name>:<tool_name>`
  - Example: `remote:google-workspace-mcp:list_users`, `remote:google-toolbox-mcp:create_task`
  - Collision detection: Warns when multiple remotes have the same tool name
  - Discovery: List all remote tools with their source remote
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections import defaultdict

from ..settings import GatewaySettings, RemoteBackendSettings


@dataclass
class RemoteToolInfo:
    """Information about a single tool on a remote MCP."""

    remote_name: str
    remote_namespace: str
    tool_name: str
    full_name: str  # e.g., "remote:google-workspace-mcp:list_users"
    description: str | None = None
    input_schema: dict[str, Any] | None = None


@dataclass
class ToolCollision:
    """Represents a tool name collision across remotes."""

    tool_name: str  # e.g., "list_users"
    remotes: list[str]  # e.g., ["google-workspace-mcp", "google-toolbox-mcp"]
    count: int


class RemoteToolNamespace:
    """Manages tool namespacing and collision detection across remotes."""

    NAMESPACE_SEPARATOR = ":"
    NAMESPACE_PREFIX = "remote"

    def __init__(self, gateway: GatewaySettings):
        self.gateway = gateway
        self._tools_cache: dict[str, list[RemoteToolInfo]] = {}  # remote_name -> tools
        self._collisions_cache: dict[str, ToolCollision] | None = None

    @staticmethod
    def make_full_name(remote_name: str, tool_name: str) -> str:
        """Create a globally unique tool name: remote:<remote_name>:<tool_name>."""
        return f"{RemoteToolNamespace.NAMESPACE_PREFIX}{RemoteToolNamespace.NAMESPACE_SEPARATOR}{remote_name}{RemoteToolNamespace.NAMESPACE_SEPARATOR}{tool_name}"

    @staticmethod
    def parse_full_name(full_name: str) -> tuple[str, str] | None:
        """Parse 'remote:<remote_name>:<tool_name>' back into (remote_name, tool_name).

        Returns None if the format is invalid.
        """
        parts = full_name.split(RemoteToolNamespace.NAMESPACE_SEPARATOR)
        if len(parts) != 3:
            return None
        if parts[0] != RemoteToolNamespace.NAMESPACE_PREFIX:
            return None
        return (parts[1], parts[2])

    @staticmethod
    def is_namespaced_tool(name: str) -> bool:
        """Check if a tool name is in the namespaced format."""
        return name.startswith(f"{RemoteToolNamespace.NAMESPACE_PREFIX}{RemoteToolNamespace.NAMESPACE_SEPARATOR}")

    def build_remote_tool_info(
        self,
        remote_name: str,
        tool_name: str,
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> RemoteToolInfo:
        """Create RemoteToolInfo for a single tool."""
        remote = next((r for r in self.gateway.remotes if r.name == remote_name), None)
        remote_namespace = remote.namespace if remote else remote_name

        return RemoteToolInfo(
            remote_name=remote_name,
            remote_namespace=remote_namespace,
            tool_name=tool_name,
            full_name=self.make_full_name(remote_name, tool_name),
            description=description,
            input_schema=input_schema,
        )

    def detect_collisions(self) -> dict[str, ToolCollision]:
        """Detect tool name collisions across all remote tools.

        Returns a dict mapping colliding tool name -> ToolCollision info.
        Example: {"list_users": ToolCollision(tool_name="list_users", remotes=["google-workspace-mcp", "google-toolbox-mcp"], count=2)}
        """
        if self._collisions_cache is not None:
            return self._collisions_cache

        tool_by_name: dict[str, list[str]] = defaultdict(list)

        # For each remote, assume we could load its tools; group by bare tool name
        for remote in self.gateway.remotes:
            if not remote.enabled:
                continue
            # Note: In actual usage, this would be called after tools are populated in _tools_cache
            # For now, we provide the infrastructure; actual tool lists come from async list_remote_tools()
            if remote.name in self._tools_cache:
                for tool in self._tools_cache[remote.name]:
                    tool_by_name[tool.tool_name].append(remote.name)

        collisions = {}
        for tool_name, remotes in tool_by_name.items():
            if len(remotes) > 1:
                collisions[tool_name] = ToolCollision(
                    tool_name=tool_name,
                    remotes=remotes,
                    count=len(remotes),
                )

        self._collisions_cache = collisions
        return collisions

    def add_remote_tools(self, remote_name: str, tools: list[RemoteToolInfo]) -> None:
        """Register tools for a remote. Used to populate cache during discovery."""
        self._tools_cache[remote_name] = tools
        self._collisions_cache = None  # Invalidate collision cache

    def get_remote_tools(self, remote_name: str) -> list[RemoteToolInfo]:
        """Get all tools for a single remote."""
        return self._tools_cache.get(remote_name, [])

    def get_all_remote_tools(self) -> dict[str, list[RemoteToolInfo]]:
        """Get all remote tools organized by remote name."""
        return self._tools_cache.copy()

    def find_tool_by_full_name(self, full_name: str) -> RemoteToolInfo | None:
        """Look up a tool by its full namespaced name.

        Example: find_tool_by_full_name("remote:google-workspace-mcp:list_users")
        """
        parsed = self.parse_full_name(full_name)
        if parsed is None:
            return None

        remote_name, tool_name = parsed
        for tool in self.get_remote_tools(remote_name):
            if tool.tool_name == tool_name:
                return tool
        return None

    def find_tool_by_base_name(self, tool_name: str) -> list[RemoteToolInfo]:
        """Find all tools matching a base name (useful for collision detection).

        Example: find_tool_by_base_name("list_users") might return tools from
        google-workspace-mcp and google-toolbox-mcp if both define list_users.
        """
        results = []
        for tools in self._tools_cache.values():
            for tool in tools:
                if tool.tool_name == tool_name:
                    results.append(tool)
        return results

    def get_collision_summary(self) -> str:
        """Generate a human-readable summary of tool collisions."""
        collisions = self.detect_collisions()
        if not collisions:
            return "No tool name collisions detected."

        lines = [f"Tool name collisions detected ({len(collisions)} total):"]
        for tool_name, collision in sorted(collisions.items()):
            lines.append(f"  • '{tool_name}' found in: {', '.join(sorted(collision.remotes))}")
        lines.append("\nUse full names to disambiguate:")
        for tool_name, collision in sorted(collisions.items()):
            for remote_name in sorted(collision.remotes):
                full = RemoteToolNamespace.make_full_name(remote_name, tool_name)
                lines.append(f"  • {full}")
        return "\n".join(lines)
