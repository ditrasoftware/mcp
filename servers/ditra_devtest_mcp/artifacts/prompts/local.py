"""Context-sampled prompts demonstrating FastMCP 4.0.x patterns.

Prompts show:
- Context sampling: request tenant, roles, recent history
- Template composition
- Progressive disclosure for enterprise workflows
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
import mcp.types as mt

from ...middleware.tenant_resolution import TenantContext


def register_local_prompts(mcp: FastMCP, **kwargs) -> set[str]:
    """Register context-aware enterprise prompts.
    
    These demonstrate how prompts can be sampled with tenant/user context.
    """
    
    local_prompt_names: set[str] = set()
    
    @mcp.prompt()
    async def enterprise_gateway_guide() -> mt.GetPromptResult:
        """Guide for using the enterprise MCP gateway.
        
        Shows comprehensive overview of capabilities and usage patterns.
        """
        ctx = get_context()
        tenant: TenantContext | None = getattr(ctx, "tenant", None)
        
        tenant_info = ""
        if tenant:
            tenant_info = f"\n\n**Your Tenant Context:**\n- ID: {tenant.id}\n- Name: {tenant.name}\n- Tier: {tenant.tier}\n- Scopes: {', '.join(tenant.scopes)}"
        
        content = f"""# Enterprise MCP Gateway Guide

## Overview

Welcome to the enterprise MCP gateway. This is a federated system that orchestrates multiple domain-specific MCPs:

- **anticafarmacia_mcp** - Pharmacy and patient management
- **ferreromed_mcp** - Medical devices and logistics
- **lottomaticapss_mcp** - Point-of-sale and transactions

## Key Capabilities

### Local Tools (Enterprise Control Plane)
1. **local_auth_debug** - Check your authentication and tenant context
2. **local_gateway_summary** - Overview of all capabilities
3. **local_capability_inspect** - Deep dive into specific capabilities
4. **local_error_taxonomy_lookup** - Understand error handling
5. **local_sample_patient_search** - Search patient records
6. **local_sample_order_create** - Create orders with tracking

### Middleware-Enforced Guarantees

All tool calls pass through this middleware stack:
1. **Observability** - Request tracking with unique IDs
2. **Tenant Resolution** - Extract and validate tenant context
3. **Auth Enforcement** - Check scopes and access policies
4. **Error Normalization** - Consistent error taxonomy

### Resources (Discovery & Diagnostics)

- `ditra://health` - Service health and capabilities
- `ditra://gateway/remotes` - Available remote adapters
- `ditra://capability-registry` - Complete capability export
- `ditra://error-taxonomy` - Error reference documentation
- `ditra://sample/patients/{{patient_id}}` - Sample patient records

## Common Workflows

### 1. Check Your Access
```
Call: local_auth_debug
Returns: Your tenant, roles, scopes, and access tier
```

### 2. Discover Available Tools
```
Call: local_gateway_summary
Returns: Count of local + remote tools, middleware status
```

### 3. Inspect a Specific Capability
```
Call: local_capability_inspect with capability_id="local.sample.patient.search"
Returns: Full contract including input/output schemas, auth requirements, error handling
```

### 4. Search for Patient Data
```
Call: local_sample_patient_search with query="Alice" limit=10
Returns: Matching patient records (tenant-scoped)
```

### 5. Create an Order
```
Call: local_sample_order_create with patient_id="PAT-001" product_name="Insulin" quantity=1
Returns: Order ID with tracking information and estimated delivery
```

## Error Handling

All errors follow the enterprise error taxonomy:

- **VALIDATION_ERROR** - Input validation failed
- **AUTH_ERROR** - Authentication or authorization failed
- **NOT_FOUND_ERROR** - Resource not found
- **PROVIDER_ERROR** - Remote service unavailable
- ... and 10+ other categories (use local_error_taxonomy_lookup to explore)

Each error includes:
- `category` - Standardized error type
- `code` - Specific error code for programmatic handling
- `message` - Human-readable description
- `recoverable` - Whether the client should retry
- `tenant_id` - Which tenant the error occurred for

## Tenant-Scoped Access

All tools and resources are automatically scoped to your tenant:
- You can only see your tenant's data
- Errors indicate your tenant context
- Audit logs track all access per tenant
{tenant_info}

## Next Steps

1. Call `local_auth_debug` to verify your access
2. Call `local_gateway_summary` to see available tools
3. Try `local_sample_patient_search` with a test query
4. Explore `local_capability_inspect` for detailed contracts

## Support

- Error returned? Call `local_error_taxonomy_lookup` with the error category
- Need capability details? Use `local_capability_inspect`
- Check service health? Read `ditra://health` resource
"""
        
        return mt.GetPromptResult(
            description="Comprehensive guide for using the enterprise MCP gateway",
            messages=[
                mt.PromptMessage(
                    role="user",
                    content=mt.TextContent(type="text", text=content),
                )
            ],
        )
    
    local_prompt_names.add("enterprise_gateway_guide")
    
    @mcp.prompt()
    async def patient_intake_workflow() -> mt.GetPromptResult:
        """Prompt for patient intake workflow.
        
        Guides user through creating a new patient and order.
        """
        content = """# Patient Intake Workflow

## Steps

### 1. Prepare Patient Information
Gather the following details about the new patient:
- Full name
- Date of birth (YYYY-MM-DD format)
- Email address
- Phone number
- Insurance information (if applicable)

### 2. Create Patient Record
Use `local_sample_patient_search` to check if patient already exists:
```
Call: local_sample_patient_search
Query: "[patient name]"
Result: Returns matching patients if found
```

If patient exists, note their **patient_id** (format: PAT-###)

### 3. Determine Products/Services
Based on patient's needs, identify the required products:
- Medications (from ferreromed_mcp)
- Medical devices (from ferreromed_mcp)
- Pharmacy items (from anticafarmacia_mcp)

### 4. Create Order
Use `local_sample_order_create`:
```
Call: local_sample_order_create
Args:
  - patient_id: "PAT-001"
  - product_name: "Insulin Vial 10mL"
  - quantity: 1
Result: Returns order_id with tracking details
```

### 5. Track Delivery
Use the order_id to track shipment status via ferreromed_mcp logistics adaptor

## Example Session

**User:** I need to order Insulin for Alice Johnson

**Step 1:** Call `local_sample_patient_search` with query="Alice Johnson"
**Result:** PAT-001 found, active patient

**Step 2:** Call `local_sample_order_create` with:
- patient_id: PAT-001
- product_name: Insulin Vial 10mL
- quantity: 1

**Result:**
```json
{
  "order_id": "ORD-A7F2E9C1",
  "patient_id": "PAT-001",
  "status": "created",
  "created_at": "2026-08-18T14:30:00Z",
  "estimated_delivery": "2026-08-25T14:00:00Z"
}
```

**Step 3:** Share order_id with patient for tracking

## Troubleshooting

**Patient not found:**
- Verify spelling of patient name
- Check if patient is archived (search may filter inactive)
- Create new patient via anticafarmacia_mcp patient_create tool

**Order creation failed:**
- Call `local_error_taxonomy_lookup` with returned error category
- Common: VALIDATION_ERROR if patient_id doesn't exist
- Common: NOT_FOUND_ERROR if product_name is unknown

## Next Steps

- Monitor order status using ferreromed_mcp tracking tools
- Update patient record if information changes
- Process payment through lottomaticapss_mcp POS system
"""
        
        return mt.GetPromptResult(
            description="Guided workflow for patient intake and order creation",
            messages=[
                mt.PromptMessage(
                    role="user",
                    content=mt.TextContent(type="text", text=content),
                )
            ],
        )
    
    local_prompt_names.add("patient_intake_workflow")
    
    @mcp.prompt()
    async def capability_contract_reference() -> mt.GetPromptResult:
        """Reference guide for capability contracts.
        
        Explains the structure of capability contracts for API consumers.
        """
        content = """# Capability Contract Reference

## What is a Capability Contract?

A capability contract is a machine-readable specification of a tool or resource:
- **What it does:** Description and purpose
- **How to call it:** Input schema (required/optional parameters)
- **What it returns:** Output schema
- **When it works:** Auth requirements, tenant scopes, reliability tier
- **What errors it raises:** Error categories and recovery options
- **How long results live:** Caching policy

## Contract Structure

```json
{
  "capability_id": "local.sample.patient.search",
  "tool_name": "local_sample_patient_search",
  "version": "1.0",
  "description": "Search for patients by name or ID",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer", "default": 10}
    },
    "required": ["query"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "count": {"type": "integer"},
      "results": {"type": "array"}
    }
  },
  "auth_profile": "tenant_scoped",
  "required_scopes": ["patient:read"],
  "reliability_tier": "tier_a",
  "error_categories": ["VALIDATION_ERROR", "NOT_FOUND_ERROR"],
  "pii_classification": "high",
  "cache_control": "private, max-age=300"
}
```

## Field Definitions

| Field | Meaning |
|-------|---------|
| `capability_id` | Unique provider-neutral identifier (e.g., "local.sample.patient.search") |
| `tool_name` | MCP tool function name |
| `version` | Semantic version |
| `description` | What the capability does |
| `input_schema` | JSON Schema for input parameters |
| `output_schema` | JSON Schema for return value |
| `auth_profile` | Required auth (e.g., "tenant_scoped", "admin_only") |
| `required_scopes` | OAuth scopes needed (e.g., "patient:read") |
| `reliability_tier` | SLA tier (tier_a=99.9%, tier_b=99%, tier_c=95%) |
| `error_categories` | Which error types this tool can raise |
| `pii_classification` | Sensitivity of returned data (none/low/medium/high) |
| `cache_control` | HTTP cache directives (RFC 7234) |

## How to Use Contracts

### 1. Discovery
Call `local_capability_inspect` with any capability_id to get its full contract

### 2. Validation
Use the `input_schema` to validate your arguments before calling the tool

### 3. Error Handling
Check `error_categories` to know what errors to expect
Look up error handling in `local_error_taxonomy_lookup`

### 4. Performance
Use `cache_control` to understand caching behavior:
- `private, max-age=300` = Cache in your client for 5 minutes
- `public, immutable` = Cache forever (resource never changes)
- `no-cache` = Don't cache (always fetch fresh)

### 5. Access Control
Check `required_scopes` against your tenant's scopes (from `local_auth_debug`)
If you lack required scopes, your call will fail with AUTH_ERROR

## Example: Implementing a Client

```python
from mcp_client import MCPClient

client = MCPClient()

# 1. Get capability contract
contract = client.call("local_capability_inspect", 
                       capability_id="local.sample.patient.search")

# 2. Validate your input against contract
def validate_search(query, limit):
    if not isinstance(query, str) or not query:
        raise ValueError("query must be non-empty string")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be positive integer")

# 3. Call the tool
result = client.call("local_sample_patient_search", 
                    query="Alice", 
                    limit=10)

# 4. Handle errors using error taxonomy
if "error" in result:
    error_category = result.get("error_category")
    if error_category == "NOT_FOUND_ERROR":
        print("No patients found")
    elif error_category == "VALIDATION_ERROR":
        print("Invalid search parameters")
    # ... etc

# 5. Respect cache-control directives
cache_control = contract.cache_control
if "max-age" in cache_control:
    ttl = int(cache_control.split("max-age=")[1])
    client.cache(result, ttl=ttl)
```

## Contract Versioning

Contracts follow semantic versioning:
- **MAJOR** (1.0 → 2.0): Breaking changes (output schema changes)
- **MINOR** (1.0 → 1.1): New optional input parameters, new optional output fields
- **PATCH** (1.0.0 → 1.0.1): Bugfixes, no schema changes

Always check the `version` field. If you depend on a specific contract, pin the version.

## Next Steps

1. Call `local_capability_inspect` to see real contracts
2. Call `local_gateway_summary` to list all available capabilities
3. Use `enterprise_gateway_guide` for workflow examples
"""
        
        return mt.GetPromptResult(
            description="Reference guide explaining capability contracts",
            messages=[
                mt.PromptMessage(
                    role="user",
                    content=mt.TextContent(type="text", text=content),
                )
            ],
        )
    
    local_prompt_names.add("capability_contract_reference")
    
    return local_prompt_names
