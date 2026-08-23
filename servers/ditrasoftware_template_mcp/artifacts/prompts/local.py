"""Template for context-sampled prompts.

TODO: Replace these example prompts with your own.

FastMCP 4.0.x patterns:
- Prompts can access tenant/user context via get_context()
- Use GetPromptResult with PromptMessage list
- Context-sample prompt content based on tenant tier, user role, etc.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
import mcp.types as mt


def register_local_prompts(mcp: FastMCP, **kwargs) -> set[str]:
    """Register your context-aware prompts.
    
    TODO: Implement your prompts here using @mcp.prompt() decorator.
    """
    
    local_prompt_names: set[str] = set()
    
    # EXAMPLE 1: Simple getting started prompt
    @mcp.prompt()
    async def getting_started_guide() -> mt.GetPromptResult:
        """Getting started guide with your MCP.
        
        TODO: Customize with your domain and use cases.
        """
        # TODO: Access tenant context like this:
        # ctx = get_context()
        # tenant = getattr(ctx, "tenant", None)
        # if tenant and tenant.tier == "enterprise":
        #     # Show advanced features
        # else:
        #     # Show basic features
        
        content = """# Getting Started

## Welcome

You're now connected to the enterprise MCP system.

## Next Steps

1. Call `hello_world` to verify connectivity
2. Call `get_tenant_context` to see your tenant info
3. Explore available resources
4. Implement your business logic

## Resources

- TODO: Add links to your documentation
- TODO: Add links to your support channels

## Questions?

TODO: Add your support information here.
"""
        
        return mt.GetPromptResult(
            description="Getting started guide for your MCP",
            messages=[
                mt.PromptMessage(
                    role="user",
                    content=mt.TextContent(type="text", text=content),
                )
            ],
        )
    
    local_prompt_names.add("getting_started_guide")
    
    # TODO: Add your real prompts below
    # @mcp.prompt()
    # async def your_workflow_prompt() -> mt.GetPromptResult:
    #     \"\"\"Prompt for your specific workflow.
    #     
    #     TODO: Describe your workflow here.
    #     \"\"\"
    #     ctx = get_context()
    #     tenant = getattr(ctx, "tenant", None)
    #     
    #     content = f\"\"\"# Your Workflow
    #     
    # ## For Tenant: {tenant.name if tenant else 'Unknown'}
    # 
    # TODO: Add workflow steps here
    # \"\"\"
    #     
    #     return mt.GetPromptResult(
    #         description="Your workflow guide",
    #         messages=[
    #             mt.PromptMessage(
    #                 role="user",
    #                 content=mt.TextContent(type="text", text=content),
    #             )
    #         ],
    #     )
    # 
    # local_prompt_names.add("your_workflow_prompt")
    
    return local_prompt_names
