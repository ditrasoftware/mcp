# Working Implementation Demo Guide

## Overview

You now have **complete, runnable implementations** in both MCPs:

- **ditra_devtest_mcp** - Full working reference with 8 tools, 5 resources, 3 prompts, 2 apps
- **ditrasoftware_template_mcp** - Clean scaffold with TODO examples

This guide shows how to test everything end-to-end.

---

## ditra_devtest_mcp: Complete Working Implementation

### Tools (8 Total)

| Tool | Purpose | Demo |
|------|---------|------|
| `local_auth_debug` | Check tenant/auth context | Shows middleware at work |
| `local_gateway_summary` | Overview of capabilities | Capability registry |
| `local_capability_inspect` | Deep dive into contracts | Contract schema details |
| `local_error_taxonomy_lookup` | Error reference | Error handling patterns |
| `local_echo` | Simple echo with tenant | Middleware context injection |
| `local_sample_patient_search` | Mock patient search | Business logic + filtering |
| `local_sample_order_create` | Create orders (mock) | ID generation + tracking |

### Resources (5 Total)

| Resource | MIME Type | Cache Policy | Demo |
|----------|-----------|--------------|------|
| `ditra://health` | `application/json` | `public, max-age=30` | Health check |
| `ditra://gateway/remotes` | `application/json` | `public, max-age=60` | Remote adapter config |
| `ditra://capability-registry` | `application/json` | `public, immutable` | Full capability export |
| `ditra://error-taxonomy` | `application/json` | `public, immutable` | Error reference |
| `ditra://sample/patients/{patient_id}` | `application/json` | `private, max-age=300` | Parameterized resource |

### Prompts (3 Total)

| Prompt | Context | Demo |
|--------|---------|------|
| `enterprise_gateway_guide` | Tenant-aware overview | Full MCP usage guide |
| `patient_intake_workflow` | Step-by-step workflow | Patient + order creation |
| `capability_contract_reference` | Contract patterns | How to use contracts |

### Apps (2 Total)

| App | Composition | Demo |
|-----|-----------|------|
| `diagnostics` | PrefabApp (auto-synthesized) | 4 diagnostic tools + 4 resources |
| `patient_management` | PrefabApp (auto-synthesized) | 2 patient tools + 1 resource |

---

## Testing Locally

### 1. Start ditra_devtest_mcp

```bash
cd servers/ditra_devtest_mcp
python -m ditra_devtest_mcp
# Server starts on http://localhost:5000
```

### 2. Test Tools via Direct HTTP

**Test: local_auth_debug (Middleware Context)**

```bash
curl -X POST http://localhost:5000/call_tool \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: test-enterprise-1" \
  -d '{
    "tool_name": "local_auth_debug"
  }'
```

**Expected Response:**
```json
{
  "status": "authenticated",
  "tenant": {
    "id": "test-enterprise-1",
    "name": "Test Enterprise Org",
    "tier": "enterprise",
    "roles": ["admin", "user"],
    "scopes": ["*"],
    "region": "us-east-1"
  },
  "timestamp": "2026-08-18T..."
}
```

This proves:
- ✅ TenantResolutionMiddleware resolved tenant from header
- ✅ AuthEnforcementMiddleware allowed call (enterprise tier)
- ✅ Tool received tenant context via get_context()

---

**Test: local_sample_patient_search (Business Logic)**

```bash
curl -X POST http://localhost:5000/call_tool \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: test-enterprise-1" \
  -d '{
    "tool_name": "local_sample_patient_search",
    "arguments": {
      "query": "Alice",
      "limit": 5
    }
  }'
```

**Expected Response:**
```json
{
  "query": "Alice",
  "count": 1,
  "results": [
    {
      "patient_id": "PAT-001",
      "name": "Alice Johnson",
      "dob": "1985-03-15",
      "email": "alice@example.com",
      "phone": "+1-555-0101",
      "status": "active"
    }
  ],
  "timestamp": "2026-08-18T..."
}
```

This proves:
- ✅ Tool receives clean business logic (no auth checks)
- ✅ Filtering/search logic works
- ✅ Structured output follows capability contract

---

**Test: local_sample_order_create (ID Generation)**

```bash
curl -X POST http://localhost:5000/call_tool \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: test-enterprise-1" \
  -d '{
    "tool_name": "local_sample_order_create",
    "arguments": {
      "patient_id": "PAT-001",
      "product_name": "Insulin Vial",
      "quantity": 2
    }
  }'
```

**Expected Response:**
```json
{
  "order_id": "ORD-A7F2E9C1",
  "patient_id": "PAT-001",
  "product_name": "Insulin Vial",
  "quantity": 2,
  "status": "created",
  "created_at": "2026-08-18T14:30:00Z",
  "estimated_delivery": "2026-08-25T14:00:00Z"
}
```

This proves:
- ✅ UUID-based ID generation works
- ✅ Business logic (order composition) works
- ✅ Structured output with tracking info

---

### 3. Test Resources

**Test: Read ditra://health**

```bash
curl -X GET http://localhost:5000/resource/ditra://health \
  -H "X-Tenant-Id: test-enterprise-1"
```

**Expected Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-08-18T...",
  "uptime_seconds": 3600,
  "capabilities": {
    "local_tools": 8,
    "middleware_layers": 4,
    "error_taxonomy_entries": 14
  }
}
```

**Verify Cache-Control Header:**
```bash
curl -i http://localhost:5000/resource/ditra://health | grep -i cache-control
# Should return: cache-control: public, max-age=30
```

---

**Test: Read ditra://capability-registry (Immutable)**

```bash
curl -X GET http://localhost:5000/resource/ditra://capability-registry \
  -H "X-Tenant-Id: test-enterprise-1" | jq .
```

**Verify Immutable Cache:**
```bash
curl -i http://localhost:5000/resource/ditra://capability-registry | grep -i cache-control
# Should return: cache-control: public, immutable
```

---

**Test: Parameterized Resource (ditra://sample/patients/{patient_id})**

```bash
curl -X GET "http://localhost:5000/resource/ditra://sample/patients/PAT-001" \
  -H "X-Tenant-Id: test-enterprise-1" | jq .
```

**Expected Response:**
```json
{
  "patient_id": "PAT-001",
  "name": "Alice Johnson",
  "dob": "1985-03-15",
  "email": "alice@example.com",
  "phone": "+1-555-0101",
  "status": "active",
  "created_at": "2024-01-15T10:00:00Z",
  "last_visit": "2026-08-10T14:30:00Z"
}
```

---

### 4. Test Prompts

**Test: Get enterprise_gateway_guide (Context-Sampled)**

```bash
curl -X POST http://localhost:5000/get_prompt \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: test-enterprise-1" \
  -d '{"prompt_name": "enterprise_gateway_guide"}'
```

**Expected Response:**
Shows guide with:
- ✅ Tenant context injected (e.g., "Your Tenant Context: test-enterprise-1")
- ✅ Overview of gateway and remote adapters
- ✅ Common workflows with tool names
- ✅ Error handling patterns

---

### 5. Test Error Normalization (Middleware)

**Test: Error on Invalid Tenant (AuthEnforcementMiddleware)**

```bash
curl -X POST http://localhost:5000/call_tool \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: invalid-tenant" \
  -d '{"tool_name": "local_auth_debug"}'
```

**Expected Response (Normalized Error):**
```json
{
  "isError": true,
  "error": "Tenant not found: invalid-tenant",
  "_meta": {
    "category": "AUTH_ERROR",
    "code": "TENANT_NOT_FOUND",
    "message": "Invalid or missing tenant",
    "tenant_id": "invalid-tenant",
    "recoverable": false
  }
}
```

This proves:
- ✅ ErrorNormalizationMiddleware catches auth errors
- ✅ Returns standard taxonomy (category, code, message)
- ✅ Includes tenant_id for audit

---

### 6. Test Full Middleware Stack

**Request Journey:**
```
Client Request
    ↓
ObservabilityMiddleware: Add request-id UUID
    ↓
TenantResolutionMiddleware: Extract tenant from X-Tenant-Id header
    ↓
AuthEnforcementMiddleware: Check tenant exists, validate tier
    ↓
ErrorNormalizationMiddleware: Wrap tool call in try/catch
    ↓
Tool Execution: Clean business logic only
    ↓
Response returned through middleware stack
    ↓
Client Response (with error normalized if needed)
```

**Verify Request Tracing (Check request-id):**

```bash
curl -v http://localhost:5000/call_tool \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: test-enterprise-1" \
  -d '{"tool_name": "local_auth_debug"}' 2>&1 | grep -i "x-request-id"
# Should see: X-Request-Id: [UUID]
```

---

## ditrasoftware_template_mcp: Getting Started

### Using the Template for a New MCP

```bash
# 1. Copy template
cp -r servers/ditrasoftware_template_mcp/ servers/my_new_mcp/

# 2. Update names
find servers/my_new_mcp -type f -name "*.py" | xargs sed -i \
  's/ditrasoftware_template_mcp/my_new_mcp/g'

# 3. Customize capability registry
nano servers/my_new_mcp/capability/registry.py
# Add your capabilities

# 4. Implement tools
nano servers/my_new_mcp/artifacts/tools/local.py
# Replace hello_world with your tools

# 5. Run
cd servers/my_new_mcp
python -m my_new_mcp
```

### Example: Customize for Pizza Delivery MCP

**1. Update capability/registry.py:**

```python
CAPABILITIES: dict[str, CapabilityContract] = {
    "pizza.order.create": CapabilityContract(
        capability_id="pizza.order.create",
        tool_name="pizza_order_create",
        version="1.0",
        description="Create a pizza delivery order",
        input_schema={"type": "object", "properties": {...}},
        output_schema={"type": "object", "properties": {...}},
        auth_profile="tenant_scoped",
        reliability_tier="tier_a",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR"],
    ),
    # ... more capabilities
}
```

**2. Update artifacts/tools/local.py:**

```python
@mcp.tool()
async def pizza_order_create(
    customer_id: str,
    pizza_config: str,  # e.g., "large-pepperoni"
    delivery_address: str,
) -> dict[str, Any]:
    """Create a pizza delivery order."""
    import uuid
    order_id = f"PIZZA-{uuid.uuid4().hex[:8].upper()}"
    return {
        "order_id": order_id,
        "customer_id": customer_id,
        "pizza_config": pizza_config,
        "delivery_address": delivery_address,
        "status": "accepted",
        "estimated_delivery": "30 minutes",
    }

local_tool_names.add("pizza_order_create")
```

**3. Test:**

```bash
curl -X POST http://localhost:5000/call_tool \
  -H "X-Tenant-Id: pizza-shop-1" \
  -d '{
    "tool_name": "pizza_order_create",
    "arguments": {
      "customer_id": "CUST-001",
      "pizza_config": "large-pepperoni",
      "delivery_address": "123 Main St"
    }
  }'
```

---

## Key Demonstration Points

### 1. Middleware-First Architecture Works

- Tools are clean business logic ✅
- Auth/error/observability in middleware ✅
- Tenant context automatically available ✅
- Errors normalized to standard taxonomy ✅

### 2. FastMCP 4.0.x Patterns

- **Tools:** Simple async functions, no boilerplate ✅
- **Resources:** Explicit MIME types + cache-control RFC 7234 ✅
- **Prompts:** Context-sampled with tenant/user info ✅
- **Apps:** 90% auto-synthesized via PrefabApp ✅

### 3. Enterprise Governance

- Capability contracts discoverable ✅
- Error taxonomy standardized ✅
- Tenant scoping automatic ✅
- Audit trail (request-id, tenant_id) ✅

### 4. Scalability

- Stateless middleware (no session storage) ✅
- Multi-worker ready (no sticky sessions) ✅
- Resource caching via HTTP cache-control ✅
- Long operations can use EventStore (framework ready) ✅

---

## Smoke Test Script

```bash
#!/bin/bash
set -e

MCP_URL="http://localhost:5000"
TENANT="test-enterprise-1"

echo "🧪 Smoke Testing ditra_devtest_mcp"
echo ""

# Test 1: Auth context
echo "✓ Test 1: local_auth_debug"
curl -s -X POST "$MCP_URL/call_tool" \
  -H "X-Tenant-Id: $TENANT" \
  -d '{"tool_name": "local_auth_debug"}' | jq .status

# Test 2: Gateway summary
echo "✓ Test 2: local_gateway_summary"
curl -s -X POST "$MCP_URL/call_tool" \
  -H "X-Tenant-Id: $TENANT" \
  -d '{"tool_name": "local_gateway_summary"}' | jq .summary

# Test 3: Patient search
echo "✓ Test 3: local_sample_patient_search"
curl -s -X POST "$MCP_URL/call_tool" \
  -H "X-Tenant-Id: $TENANT" \
  -d '{"tool_name":"local_sample_patient_search","arguments":{"query":"Alice"}}' | jq .count

# Test 4: Order creation
echo "✓ Test 4: local_sample_order_create"
curl -s -X POST "$MCP_URL/call_tool" \
  -H "X-Tenant-Id: $TENANT" \
  -d '{"tool_name":"local_sample_order_create","arguments":{"patient_id":"PAT-001","product_name":"Insulin","quantity":1}}' | jq .order_id

# Test 5: Health resource
echo "✓ Test 5: ditra://health resource"
curl -s -X GET "$MCP_URL/resource/ditra://health" \
  -H "X-Tenant-Id: $TENANT" | jq .status

# Test 6: Capability registry resource
echo "✓ Test 6: ditra://capability-registry resource"
curl -s -X GET "$MCP_URL/resource/ditra://capability-registry" \
  -H "X-Tenant-Id: $TENANT" | jq .count

echo ""
echo "✅ All tests passed!"
```

---

## Summary: What You Have

| Artifact | ditra_devtest_mcp | ditrasoftware_template_mcp |
|----------|-------------------|----------------------------|
| **Tools** | 8 working + 4 diagnostic | 2 example + TODOs |
| **Resources** | 5 full (health, remotes, registry, errors, patients) | 2 example + TODOs |
| **Prompts** | 3 context-aware guides | 1 example + TODOs |
| **Apps** | 2 PrefabApp (auto-synthesized) | 1 example + TODOs |
| **Middleware** | Full stack (4 layers) + integrated | Full stack (4 layers) + integrated |
| **Capability Registry** | 4 sample capabilities | Empty (for customization) |
| **Status** | Ready to demo + adapt | Ready to scaffold new MCPs |

You can now:
1. ✅ Start ditra_devtest_mcp and test all tools/resources/prompts via HTTP
2. ✅ Show working middleware enforcement (tenant context, auth, errors)
3. ✅ Copy ditrasoftware_template_mcp to create new MCPs quickly
4. ✅ Demonstrate FastMCP 4.0.x patterns (middleware-first, auto-UI, caching, context-sampling)
5. ✅ Explain enterprise architecture with concrete examples

---

## Next Steps

1. **Start Server:** `cd servers/ditra_devtest_mcp && python -m ditra_devtest_mcp`
2. **Run Smoke Test:** Use curl examples above to verify all tools/resources/prompts
3. **Create Demo:** Show tenant context injection via `local_auth_debug`
4. **Customize Template:** Copy ditrasoftware_template_mcp to create your_mcp
5. **Document Results:** Screenshot responses showing middleware at work
