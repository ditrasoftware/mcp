from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def register_local_prompts(mcp: FastMCP) -> dict[str, Any]:
    """Register domain-specific prompts.
    
    TODO: Implement your domain-specific prompts here.
    
    Prompts are reusable agent templates that can provide context
    for specific use cases or workflows.
    """
    
    local_prompt_registry: dict[str, Any] = {}
    
    # TODO: Add your domain-specific prompts below
    # Example:
    # @mcp.prompt()
    # def my_prompt(context: str) -> str:
    #     \"\"\"My domain-specific prompt.\"\"\"
    #     return f"Use this context: {context}"
    #
    # local_prompt_registry["my_prompt"] = ...
    
    return local_prompt_registry
