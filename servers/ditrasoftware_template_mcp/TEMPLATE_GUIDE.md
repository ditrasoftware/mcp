# Enterprise MCP Template

This template provides a starting scaffold for building new enterprise-grade MCPs using FastMCP 4.0.x.

## Quick Start

1. **Copy this folder** as `<new_mcp_name>_mcp/` 
2. **Replace template names**:
   - `ditrasoftware_template_mcp` → your MCP name
   - `DitraTemplate` → your MCP display name
   - Update `settings.py` with your configuration

3. **Follow the structure**:
   - `middleware/` - Enterprise middleware stack (pre-built)
   - `capability/` - Capability registry and contracts (customize)
    - `artifacts/` - Canonical artifact implementations by type/source
   - `providers/adapters/` - Adapters for remote MCP dependencies
    - `providers/` - Backward-compatible wrappers for old imports
   - `server.py` - FastMCP instance setup (pre-configured with middleware)

4. **Implement your capabilities**:
   - Add tools in `artifacts/tools/local.py`
   - Add resources in `artifacts/resources/local.py`
   - Add prompts in `artifacts/prompts/local.py`
   - Add contracts in `capability/registry.py`

5. **Connect remote MCPs** (optional):
   - Create adapter in `providers/adapters/<provider>.py`
   - Implement `RemoteMCPAdapter` interface
   - Register in `server.py`

---

## File Structure

```
<mcp_name>_mcp/
├── middleware/
│   ├── __init__.py
│   ├── tenant_resolution.py        # Resolve tenant from auth/headers
│   ├── auth_enforcement.py          # Validate auth scopes
│   ├── error_normalization.py       # Convert errors to taxonomy
│   └── observability.py             # Request-id, metrics
│
├── capability/
│   ├── __init__.py
│   ├── contracts.py                 # CapabilityContract dataclass
│   ├── error_taxonomy.py            # Standard error categories
│   └── registry.py                  # Your capability definitions
│
├── artifacts/
│   ├── tools/
│   │   ├── local.py                 # @mcp.tool() implementations
│   │   └── federated.py             # Remote/federated tools (optional)
│   ├── resources/
│   │   ├── local.py                 # @mcp.resource() implementations
│   │   └── federated.py             # Remote/federated resources (optional)
│   ├── prompts/
│   │   ├── local.py                 # @mcp.prompt() implementations
│   │   └── federated.py             # Remote/federated prompts (optional)
│   └── apps/
│       ├── local.py                 # Prefab apps and local app providers
│       └── federated.py             # Remote/federated app providers (optional)
│
├── providers/
│   ├── local_tools.py               # Compatibility wrapper
│   ├── local_resources.py           # Compatibility wrapper
│   ├── local_prompts.py             # Compatibility wrapper
│   ├── local_apps.py                # Compatibility wrapper
│   └── adapters/
│       ├── base.py                  # RemoteMCPAdapter base class
│       └── <provider>.py            # Per-remote-MCP adapters
│
├── server.py                        # FastMCP setup with middleware
├── settings.py                      # Config & env
├── auth.py                          # Auth provider setup
├── oauth.py                         # OIDC/OAuth config
├── rest_client.py                   # HTTP client
│
├── docker-compose.yml               # Local dev deployment
├── Dockerfile                       # Container image
├── build.sh                         # Build & push image
├── .env_example                     # Env template
└── README.md                        # Your MCP docs
```

---

## Key Implementation Steps

### 1. Define Your Capabilities (capability/registry.py)

```python
CAPABILITIES = {
    "myfeature.action": CapabilityContract(
        capability_id="myfeature.action",
        tool_name="local_myfeature_action",
        version="1.0",
        description="What it does",
        input_schema={...},
        output_schema={...},
        auth_profile="user",
        required_scopes=["feature:read"],
        reliability_tier="tier_a",
        error_categories=["VALIDATION_ERROR", "PROVIDER_ERROR"],
    ),
}
```

### 2. Implement Tools (artifacts/tools/local.py)

```python
def register_local_tools(mcp: FastMCP, ...) -> set[str]:
    """Register your local tools."""
    
    local_tool_names = set()
    
    @mcp.tool()
    async def local_myfeature_action(param1: str) -> dict:
        """Do the action.
        
        Note: Auth is handled by middleware.
        Note: Errors are normalized by middleware.
        """
        # Just business logic here
        result = await do_something(param1)
        return result
    
    local_tool_names.add("local_myfeature_action")
    return local_tool_names
```

### 3. Connect Remote MCPs (providers/adapters/)

```python
# adapters/my_remote_mcp.py
class MyRemoteMCPAdapter(RemoteMCPAdapter):
    """Adapter for remote MyRemoteMCP."""
    
    async def list_remote_tools(self) -> list[dict]:
        # Fetch tools from remote MCP
        pass
    
    async def call_remote_tool(self, tool_name: str, arguments: dict) -> Any:
        # Call tool on remote
        pass
    
    def normalize_error(self, error: Exception) -> dict:
        # Map remote errors to taxonomy
        return {"category": "PROVIDER_ERROR", ...}
```

Then in `server.py`:

```python
def create_mcp() -> FastMCP:
    ...
    # Mount remote adapters
    remote_adapter = MyRemoteMCPAdapter(AdapterConfig(...))
    # Register tools from adapter
    ...
```

---

## Middleware Stack (Automatic)

Your MCP automatically includes:

1. **ObservabilityMiddleware** - Request tracking, metrics
2. **TenantResolutionMiddleware** - Extracts tenant from auth/headers
3. **AuthEnforcementMiddleware** - Validates scopes
4. **ErrorNormalizationMiddleware** - Converts errors to standard taxonomy
5. **FastMCP compatibility middleware** - Tool hash stripping, UI fixes

All registered in `server.py` and applied to every request.

---

## Testing

### Local Dev

```bash
cd <mcp_name>_mcp
python -m pytest tests/
```

### Docker Dev

```bash
docker-compose -f docker-compose.yml up
```

### Smoke Test

```bash
curl -X POST http://localhost:5000/mcp/tool \
  -H "Content-Type: application/json" \
  -d '{
    "name": "local_myfeature_action",
    "arguments": {"param1": "value"}
  }'
```

---

## Next Steps

- [ ] Customize capability registry (capability/registry.py)
- [ ] Implement local tools (artifacts/tools/local.py)
- [ ] Add resources if needed (artifacts/resources/local.py)
- [ ] Add prompts for AI guidance (artifacts/prompts/local.py)
- [ ] Create adapters for remote MCPs (providers/adapters/)
- [ ] Add contract tests (tests/contract/)
- [ ] Update docker-compose.yml for your environment
- [ ] Document your capabilities in README.md

---

## Customization Tips

- **Error categories**: Update `capability/error_taxonomy.py` with domain-specific errors
- **Tenant logic**: Customize `middleware/tenant_resolution.py` to load from your store
- **Auth validation**: Update `middleware/auth_enforcement.py` with your scope rules
- **Tool naming**: Override `RemoteMCPAdapter.normalize_tool_name()` per provider
- **Middleware order**: Change middleware registration order in `server.py` if needed

---

## Enterprise Features Built-In

✅ Structured error responses with categories and codes  
✅ Tenant-aware capability routing and policy  
✅ OAuth/OIDC auth enforcement  
✅ Request tracing and observability  
✅ Resource caching control  
✅ Stateless HTTP scaling (multi-worker ready)  
✅ Context-sampled prompts (framework ready)  
✅ EventStore for long operations (framework ready)  

---

## Support

For questions on enterprise MCP architecture, see:
- `ENTERPRISE_MCP_ARCHETYPE_SIMPLIFIED.md`
- `FASTMCP_4_0_X_AS_CORE_ARCHITECTURE.md`
- `MCP_ARTIFACTS_INVENTORY_AND_ALIGNMENT.md`
