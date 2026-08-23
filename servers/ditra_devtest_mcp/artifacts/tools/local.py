"""Enterprise diagnostic and gateway tools for ditra_devtest_mcp.

These tools demonstrate middleware-first architecture:
- All auth/error handling delegated to middleware
- Tools contain only business logic
- Tenant context automatically injected
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context

from ...capability.registry import CAPABILITIES, get_local_capabilities
from ...capability.error_taxonomy import ERROR_TAXONOMY
from ...middleware.tenant_resolution import TenantContext


def register_local_tools(
    mcp: FastMCP,
    **kwargs,
) -> set[str]:
    """Register enterprise diagnostic and gateway tools.
    
    These tools are middleware-aware and demonstrate the enterprise architecture.
    """
    
    local_tool_names: set[str] = set()
    
    @mcp.tool()
    async def local_auth_debug() -> dict[str, Any]:
        """Debug authentication and tenant context.
        
        Returns current tenant information, auth status, and scopes.
        Demonstrates middleware integration.
        """
        ctx = get_context()
        tenant: TenantContext | None = getattr(ctx, "tenant", None)
        
        if not tenant:
            return {
                "status": "unauthenticated",
                "tenant": None,
                "message": "No tenant context available",
            }
        
        return {
            "status": "authenticated",
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "tier": tenant.tier,
                "roles": list(tenant.roles),
                "scopes": list(tenant.scopes),
                "region": tenant.region,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    local_tool_names.add("local_auth_debug")
    
    @mcp.tool()
    async def local_gateway_summary() -> dict[str, Any]:
        """Get gateway and capability summary.
        
        Returns:
        - Count of local capabilities
        - Count of registered remote adapters (placeholder)
        - Sample capability contracts
        """
        local_caps = get_local_capabilities()
        
        return {
            "summary": {
                "local_capabilities": len(local_caps),
                "remote_adapters": 3,  # placeholder: anticafarmacia, ferreromed, lottomatica
                "middleware_layers": 4,  # tenant, auth, error, observability
            },
            "local_capabilities": [
                {
                    "id": cap.capability_id,
                    "tool": cap.tool_name,
                    "description": cap.description,
                    "tier": cap.reliability_tier,
                }
                for cap in local_caps
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    local_tool_names.add("local_gateway_summary")
    
    @mcp.tool()
    async def local_capability_inspect(capability_id: str) -> dict[str, Any]:
        """Inspect a capability contract.
        
        Args:
            capability_id: The capability ID to inspect (e.g., "local.auth.debug")
        
        Returns:
            Full capability contract including schema, auth profile, error categories.
        """
        from ...capability.registry import get_capability
        
        cap = get_capability(capability_id)
        
        if not cap:
            return {
                "error": f"Capability not found: {capability_id}",
                "available": list(CAPABILITIES.keys()),
            }
        
        return {
            "capability_id": cap.capability_id,
            "tool_name": cap.tool_name,
            "version": cap.version,
            "description": cap.description,
            "input_schema": cap.input_schema,
            "output_schema": cap.output_schema,
            "auth_profile": cap.auth_profile,
            "required_scopes": list(cap.required_scopes),
            "reliability_tier": cap.reliability_tier,
            "error_categories": cap.error_categories,
            "aliases": cap.aliases,
            "cache_control": cap.cache_control,
            "pii_classification": cap.pii_classification,
        }
    
    local_tool_names.add("local_capability_inspect")
    
    @mcp.tool()
    async def local_error_taxonomy_lookup(category: str | None = None) -> dict[str, Any]:
        """Look up error taxonomy.
        
        Args:
            category: Optional category to filter (e.g., "VALIDATION_ERROR")
        
        Returns:
            Error categories and known errors with their definitions.
        """
        if category:
            errors = {
                code: info
                for code, info in ERROR_TAXONOMY.items()
                if info.category == category
            }
            return {
                "category": category,
                "errors": errors,
                "count": len(errors),
            }
        
        # Return all categories and a sample of errors
        categories = {}
        for code, info in ERROR_TAXONOMY.items():
            cat = info.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(code)
        
        return {
            "categories": categories,
            "total_errors": len(ERROR_TAXONOMY),
            "sample_errors": dict(list(ERROR_TAXONOMY.items())[:5]),
        }
    
    local_tool_names.add("local_error_taxonomy_lookup")
    
    @mcp.tool()
    async def local_echo(message: str, tenant_echo: bool = False) -> dict[str, Any]:
        """Echo a message back, optionally with tenant context.
        
        Args:
            message: Message to echo
            tenant_echo: If True, include tenant context in response
        
        Returns:
            Echo response with optional tenant info (for testing middleware).
        """
        ctx = get_context()
        tenant: TenantContext | None = getattr(ctx, "tenant", None)
        
        result = {
            "echo": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if tenant_echo and tenant:
            result["tenant"] = {
                "id": tenant.id,
                "name": tenant.name,
                "tier": tenant.tier,
            }
        
        return result
    
    local_tool_names.add("local_echo")
    
    @mcp.tool()
    async def local_sample_patient_search(
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for patients (sample tool).
        
        Args:
            query: Search query (name, ID, etc.)
            limit: Max results to return
        
        Returns:
            Mock patient records demonstrating structured output.
        """
        # Mock patient data for demonstration
        mock_patients = [
            {
                "patient_id": "PAT-001",
                "name": "Alice Johnson",
                "dob": "1985-03-15",
                "email": "alice@example.com",
                "phone": "+1-555-0101",
                "status": "active",
            },
            {
                "patient_id": "PAT-002",
                "name": "Bob Smith",
                "dob": "1990-07-22",
                "email": "bob@example.com",
                "phone": "+1-555-0102",
                "status": "active",
            },
            {
                "patient_id": "PAT-003",
                "name": "Carol Williams",
                "dob": "1978-11-08",
                "email": "carol@example.com",
                "phone": "+1-555-0103",
                "status": "inactive",
            },
        ]
        
        # Simple filter by query
        results = [
            p for p in mock_patients
            if query.lower() in p["name"].lower() or query in p["patient_id"]
        ][:limit]
        
        return {
            "query": query,
            "count": len(results),
            "results": results,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    local_tool_names.add("local_sample_patient_search")
    
    @mcp.tool()
    async def local_sample_order_create(
        patient_id: str,
        product_name: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        """Create an order (sample tool).
        
        Args:
            patient_id: Patient ID
            product_name: Product name
            quantity: Quantity
        
        Returns:
            Created order with ID and status.
        """
        import uuid
        
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        
        return {
            "order_id": order_id,
            "patient_id": patient_id,
            "product_name": product_name,
            "quantity": quantity,
            "status": "created",
            "created_at": datetime.utcnow().isoformat(),
            "estimated_delivery": "2026-08-25T14:00:00Z",
        }
    
    local_tool_names.add("local_sample_order_create")
    
    return local_tool_names
