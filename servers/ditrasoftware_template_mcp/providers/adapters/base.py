"""Base adapter class for remote MCPs template."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass


@dataclass
class AdapterConfig:
    """Configuration for a remote MCP adapter."""
    
    provider_name: str
    remote_url: str
    auth_mode: str = "none"
    timeout_ms: int = 30_000
    retry_count: int = 3


class RemoteMCPAdapter(ABC):
    """Base class for adapters wrapping remote MCPs.
    
    TODO: Implement for your specific remote MCP.
    """
    
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.provider_name = config.provider_name
    
    @abstractmethod
    async def list_remote_tools(self) -> list[dict[str, Any]]:
        """Fetch tools from remote MCP."""
        pass
    
    @abstractmethod
    async def call_remote_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on remote MCP."""
        pass
    
    def normalize_tool_name(self, remote_tool: str) -> str:
        """Normalize remote tool name to canonical form.
        
        Override to customize naming.
        """
        return f"{self.provider_name}.{remote_tool}"
    
    def normalize_error(self, error: Exception) -> dict[str, Any]:
        """Map remote error to standard error taxonomy.
        
        Override to customize error mapping.
        """
        return {
            "category": "PROVIDER_ERROR",
            "code": type(error).__name__,
            "message": str(error),
            "recoverable": False,
        }
