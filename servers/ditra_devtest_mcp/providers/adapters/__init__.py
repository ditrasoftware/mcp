"""Remote MCP adapters for ditra_devtest_mcp.

Each adapter bridges a remote MCP (anticafarmacia, ferreromed, lottomatica, etc.)
into this enterprise master MCP.

Responsibilities per adapter:
- Auth token attachment and refresh
- Tool/resource/prompt name normalization  
- Error mapping to standard taxonomy
- Schema/parameter adaptation
- Resilience (retry, timeout, circuit-break)
"""

from .base import RemoteMCPAdapter

__all__ = ["RemoteMCPAdapter"]
