"""Template for domain-specific resources.

TODO: Replace these example resources with your own.

FastMCP 4.0.x patterns:
- Resources use ResourceContent with explicit MIME types
- Include cache-control directives (RFC 7234)
- URI templates support parameterization
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from fastmcp.resources.base import ResourceContent


def register_local_resources(mcp: FastMCP, **kwargs) -> set[str]:
    """Register your domain-specific resources.
    
    TODO: Implement your resources here using @mcp.resource() decorator.
    """
    
    local_resource_uris: set[str] = set()
    
    # EXAMPLE 1: Simple health check resource
    @mcp.resource(uri_template="yourorg://health")
    async def health_resource() -> ResourceContent:
        """Service health status.
        
        TODO: Replace with your health check logic.
        """
        health_data = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
        }
        
        return ResourceContent(
            uri="yourorg://health",
            mime_type="application/json",
            text=json.dumps(health_data, indent=2),
            cache_control="public, max-age=30",  # 30-second cache
        )
    
    local_resource_uris.add("yourorg://health")
    
    # EXAMPLE 2: Configuration resource
    @mcp.resource(uri_template="yourorg://config")
    async def config_resource() -> ResourceContent:
        """Configuration metadata.
        
        TODO: Replace with your configuration data.
        """
        config = {
            "environment": "development",
            "version": "1.0.0",
            "capabilities": ["example1", "example2"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        return ResourceContent(
            uri="yourorg://config",
            mime_type="application/json",
            text=json.dumps(config, indent=2),
            cache_control="public, immutable",  # Never changes
        )
    
    local_resource_uris.add("yourorg://config")
    
    # TODO: Add your real resources below
    # @mcp.resource(uri_template="yourorg://data/{item_id}")
    # async def your_resource(item_id: str) -> ResourceContent:
    #     \"\"\"Description of your resource.
    #     
    #     Args:
    #         item_id: Identifier for the resource
    #     
    #     Returns:
    #         ResourceContent with MIME type and cache directives
    #     \"\"\"
    #     data = {
    #         "item_id": item_id,
    #         "data": "...",
    #     }
    #     
    #     return ResourceContent(
    #         uri=f"yourorg://data/{item_id}",
    #         mime_type="application/json",
    #         text=json.dumps(data, indent=2),
    #         cache_control="private, max-age=300",  # 5 min cache
    #     )
    # 
    # local_resource_uris.add("yourorg://data/{item_id}")
    
    return local_resource_uris
