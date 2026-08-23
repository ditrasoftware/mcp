"""Enterprise resources demonstrating FastMCP 4.0.x patterns.

Resources show:
- Explicit MIME types and caching metadata (RFC 7234 cache-control)
- ResourceContent with proper typing
- Discovery endpoints for governance
"""

from __future__ import annotations

import json
from datetime import datetime

from fastmcp import FastMCP
from fastmcp.resources.base import ResourceContent


def register_local_resources(mcp: FastMCP, **kwargs) -> set[str]:
    """Register enterprise resources.
    
    These demonstrate FastMCP 4.0.x resource metadata and caching.
    """
    
    local_resource_uris: set[str] = set()
    
    @mcp.resource(uri_template="ditra://health")
    async def health_check() -> ResourceContent:
        """MCP health status and diagnostics.
        
        FastMCP 4.0.x pattern: resources include explicit mime_type and cache-control.
        """
        health = {
            "status": "healthy",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": 3600,
            "capabilities": {
                "local_tools": 8,
                "middleware_layers": 4,
                "error_taxonomy_entries": 14,
            },
        }
        
        return ResourceContent(
            uri="ditra://health",
            mime_type="application/json",
            text=json.dumps(health, indent=2),
            cache_control="public, max-age=30",  # 30-second cache
        )
    
    local_resource_uris.add("ditra://health")
    
    @mcp.resource(uri_template="ditra://gateway/remotes")
    async def gateway_remotes_config() -> ResourceContent:
        """Configuration of remote MCP adapters.
        
        Shows how the master MCP discovers downstream services.
        """
        config = {
            "remotes": [
                {
                    "name": "anticafarmacia_mcp",
                    "url": "http://localhost:5001",
                    "status": "available",
                    "version": "1.0.3",
                    "capabilities": ["patient_search", "order_create", "inventory"],
                },
                {
                    "name": "ferreromed_mcp",
                    "url": "http://localhost:5002",
                    "status": "available",
                    "version": "1.0.3",
                    "capabilities": ["pharmaceutical_lookup", "pricing", "logistics"],
                },
                {
                    "name": "lottomaticapss_mcp",
                    "url": "http://localhost:5003",
                    "status": "available",
                    "version": "1.0.3",
                    "capabilities": ["point_of_sale", "transactions", "analytics"],
                },
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        return ResourceContent(
            uri="ditra://gateway/remotes",
            mime_type="application/json",
            text=json.dumps(config, indent=2),
            cache_control="public, max-age=60",  # 1-minute cache
        )
    
    local_resource_uris.add("ditra://gateway/remotes")
    
    @mcp.resource(uri_template="ditra://capability-registry")
    async def capability_registry_export() -> ResourceContent:
        """Full capability registry export for client discovery.
        
        FastMCP 4.0.x pattern: immutable resources for schema discovery.
        """
        from ...capability.registry import CAPABILITIES
        
        capabilities = {
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0",
            "count": len(CAPABILITIES),
            "capabilities": [
                {
                    "id": cap.capability_id,
                    "tool": cap.tool_name,
                    "version": cap.version,
                    "description": cap.description,
                    "auth_profile": cap.auth_profile,
                    "reliability_tier": cap.reliability_tier,
                    "error_categories": cap.error_categories,
                }
                for cap in CAPABILITIES.values()
            ],
        }
        
        return ResourceContent(
            uri="ditra://capability-registry",
            mime_type="application/json",
            text=json.dumps(capabilities, indent=2),
            cache_control="public, immutable",  # Never changes; browser can cache forever
        )
    
    local_resource_uris.add("ditra://capability-registry")
    
    @mcp.resource(uri_template="ditra://error-taxonomy")
    async def error_taxonomy_resource() -> ResourceContent:
        """Error taxonomy reference for clients.
        
        Helps clients understand how errors are categorized and handled.
        """
        from ...capability.error_taxonomy import ERROR_TAXONOMY, ERROR_CATEGORIES
        
        taxonomy = {
            "version": "1.0",
            "timestamp": datetime.utcnow().isoformat(),
            "categories": ERROR_CATEGORIES,
            "errors": {
                code: {
                    "category": info.category,
                    "message": info.message,
                    "recoverable": info.recoverable,
                    "retry_after_ms": info.retry_after_ms,
                }
                for code, info in ERROR_TAXONOMY.items()
            },
        }
        
        return ResourceContent(
            uri="ditra://error-taxonomy",
            mime_type="application/json",
            text=json.dumps(taxonomy, indent=2),
            cache_control="public, immutable",
        )
    
    local_resource_uris.add("ditra://error-taxonomy")
    
    @mcp.resource(uri_template="ditra://sample/patients/{patient_id}")
    async def patient_sample_resource(patient_id: str) -> ResourceContent:
        """Sample patient data resource (read-only reference data).
        
        Demonstrates parameterized resources and tenant-scoped access.
        """
        # Mock patient data
        patients = {
            "PAT-001": {
                "patient_id": "PAT-001",
                "name": "Alice Johnson",
                "dob": "1985-03-15",
                "email": "alice@example.com",
                "phone": "+1-555-0101",
                "status": "active",
                "created_at": "2024-01-15T10:00:00Z",
                "last_visit": "2026-08-10T14:30:00Z",
            },
            "PAT-002": {
                "patient_id": "PAT-002",
                "name": "Bob Smith",
                "dob": "1990-07-22",
                "email": "bob@example.com",
                "phone": "+1-555-0102",
                "status": "active",
                "created_at": "2023-06-20T09:15:00Z",
                "last_visit": "2026-08-12T11:45:00Z",
            },
            "PAT-003": {
                "patient_id": "PAT-003",
                "name": "Carol Williams",
                "dob": "1978-11-08",
                "email": "carol@example.com",
                "phone": "+1-555-0103",
                "status": "inactive",
                "created_at": "2022-03-10T13:20:00Z",
                "last_visit": "2025-12-01T16:00:00Z",
            },
        }
        
        if patient_id not in patients:
            return ResourceContent(
                uri=f"ditra://sample/patients/{patient_id}",
                mime_type="application/json",
                text=json.dumps({"error": "Patient not found"}),
                cache_control="no-cache",
            )
        
        return ResourceContent(
            uri=f"ditra://sample/patients/{patient_id}",
            mime_type="application/json",
            text=json.dumps(patients[patient_id], indent=2),
            cache_control="private, max-age=300",  # 5 min cache for patient data
        )
    
    local_resource_uris.add("ditra://sample/patients/{patient_id}")
    
    return local_resource_uris
