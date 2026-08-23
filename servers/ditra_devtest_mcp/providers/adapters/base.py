"""Base class for remote MCP adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass


@dataclass
class AdapterConfig:
    """Configuration for a remote MCP adapter."""
    
    provider_name: str  # e.g., "anticafarmacia", "ferreromed"
    remote_url: str  # e.g., "http://localhost:5001"
    auth_mode: str  # "bearer" | "api_key" | "none"
    timeout_ms: int = 30_000
    retry_count: int = 3


class RemoteMCPAdapter(ABC):
    """Base class for adapters that wrap remote MCPs.
    
    Each adapter:
    1. Connects to a remote MCP (via HTTP or stdio)
    2. Wraps remote tools/resources with normalization
    3. Handles auth attachment, error mapping, resilience
    4. Registers wrapped artifacts with parent FastMCP
    """
    
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.provider_name = config.provider_name
    
    @abstractmethod
    async def list_remote_tools(self) -> list[dict[str, Any]]:
        """Fetch list of tools from remote MCP."""
        pass
    
    @abstractmethod
    async def call_remote_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the remote MCP."""
        pass
    
    @abstractmethod
    async def list_remote_resources(self) -> list[dict[str, Any]]:
        """Fetch list of resources from remote MCP."""
        pass
    
    @abstractmethod
    async def read_remote_resource(self, uri: str) -> Any:
        """Read a resource from the remote MCP."""
        pass
    
    def normalize_tool_name(self, remote_tool: str) -> str:
        """Normalize remote tool name to canonical form.
        
        Example: "list_patients" → "anticafarmacia.patient.list"
        """
        # Default: <provider>.<remote_tool>
        return f"{self.provider_name}.{remote_tool}"
    
    def normalize_error(self, error: Exception) -> dict[str, Any]:
        """Map remote error to standard error taxonomy.
        
        Returns dict with:
        - category: one of ERROR_CATEGORIES
        - code: error code
        - message: human-readable message
        - recoverable: bool
        """
        # Default: map to PROVIDER_ERROR
        return {
            "category": "PROVIDER_ERROR",
            "code": type(error).__name__,
            "message": str(error),
            "recoverable": False,
        }
