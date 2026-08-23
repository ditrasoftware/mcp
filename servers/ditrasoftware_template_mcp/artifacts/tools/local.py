"""Template for domain-specific local tools.

TODO: Replace these example tools with your own domain-specific tools.

Best practices:
- Keep tools focused on business logic only
- Let middleware handle auth/error/retry logic
- Each tool = one user-facing capability
- Use capability registry to document contracts
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastmcp import FastMCP


def register_local_tools(mcp: FastMCP, **kwargs) -> set[str]:
    """Register your domain-specific local tools.
    
    TODO: Implement your tools here using @mcp.tool() decorator.
    """
    
    local_tool_names: set[str] = set()
    
    # EXAMPLE 1: Simple diagnostic tool
    @mcp.tool()
    async def hello_world(name: str = "World") -> dict[str, Any]:
        """Hello world example tool.
        
        TODO: Replace with your first real tool.
        """
        return {
            "greeting": f"Hello, {name}!",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    local_tool_names.add("hello_world")
    
    # EXAMPLE 2: Tool using context (tenant from middleware)
    @mcp.tool()
    async def get_tenant_context() -> dict[str, Any]:
        """Get current tenant context.
        
        Demonstrates access to tenant info injected by middleware.
        TODO: Add your tenant-aware business logic.
        """
        from fastmcp.server.dependencies import get_context
        
        ctx = get_context()
        tenant = getattr(ctx, "tenant", None)
        
        return {
            "tenant_id": tenant.id if tenant else None,
            "tenant_name": tenant.name if tenant else None,
            "authenticated": tenant is not None,
        }
    
    local_tool_names.add("get_tenant_context")
    
    # TODO: Add your real tools below
    # @mcp.tool()
    # async def your_first_tool(param1: str, param2: int = 10) -> dict[str, Any]:
    #     \"\"\"Your first real tool.
    #     
    #     Args:
    #         param1: Description
    #         param2: Optional parameter with default
    #     
    #     Returns:
    #         Dictionary with results
    #     \"\"\"
    #     # Your business logic here
    #     return {
    #         "param1": param1,
    #         "param2": param2,
    #         "result": "..."
    #     }
    # 
    # local_tool_names.add("your_first_tool")
    
    return local_tool_names
