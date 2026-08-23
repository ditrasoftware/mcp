# FastMCP 4.0.x as Core Architecture Primitive
## Impact on MCP Artifacts Organization, Simplification & Enterprise Archetype

---

## 1. How FastMCP 4.0.x Changes the Game

### 1.1 **Key Capabilities That Reshape Artifact Thinking**

| FastMCP 4.0.x Feature | Impact on Artifacts | Change to Archetype |
|---|---|---|
| Stateless HTTP + multi-worker | Tools/resources/prompts must be idempotent; no in-process state | Simplifies: no session stickiness, easier horizontal scale |
| Middleware composition | Auth, policy, error normalization → middleware layers | **Changes: move concerns out of tool impl, into middleware** |
| Routing headers (Mcp-Method, Mcp-Name, Mcp-Param-*) | Capability routing by metadata | **Changes: encode routing hints in capability contracts** |
| Prefab UI synthesis | Auto-generates tool UI from schema | **Changes: rethink PrefabApp; most tools get free UI** |
| EventStore for long operations | Progress persistence across SSE/polling resets | **Changes: design long tools as event-sourced workflows** |
| Modern protocol negotiation | Client auto-upgrades to 4.0; fallback to legacy | **Changes: optimize for modern; legacy is graceful fallback** |
| Response caching (modern) | Client-side cache on list operations | **Changes: list resources/tools optimized for caching** |
| OAuth mounting invariant | base_url + mcp_path must stay valid | **Changes: enforce in startup validation** |

### 1.2 **What This Means**

FastMCP 4.0.x is designed for **federated enterprise AI**, which is exactly your archetype goal.

You shouldn't think of it as "FastMCP is the runtime and your archetype is the policy layer."

Instead: **Your archetype IS FastMCP 4.0.x-native**.

---

## 2. Artifact Redesign With FastMCP 4.0.x as Core

### 2.1 **Tools: From Monolithic to Middleware-Aware**

**Old pattern (current):**
```python
@mcp.tool()
async def local_api_get(path: str, access_token: str = None, api_key: str = None, ctx: Context = None) -> Any:
    """Issue a GET request."""
    # Inside tool: auth resolution, error mapping, retries
    header_auth = _header_auth(ctx)
    effective = header_auth.merged(_auth_from_args(access_token, api_key))
    effective = _apply_default_auth(effective)
    return await client.request("GET", path, auth=effective)
```

**FastMCP 4.0.x-native pattern:**
```python
@mcp.tool()
async def local_api_get(path: str) -> dict[str, Any]:
    """Issue a GET request.
    
    Auth: resolved by middleware from request context.
    Errors: normalized by middleware into structured categories.
    Retries: handled by middleware circuit-breaker.
    """
    # Tool logic is clean: just the business logic
    return await client.request("GET", path)
```

**Why this matters:**
- Middleware intercepts all tool calls
- Can inject auth, policy, error handling uniformly
- Tools are simpler and more testable
- Concerns (auth, policy, observability) scale horizontally

### 2.2 **Resources: Cacheable by Design**

**Old pattern (current):**
```python
@mcp.resource("anticafarmacia://health")
async def health() -> dict[str, Any]:
    """Static health/config view."""
    return { "service": "AnticaFarmacia MCP", ... }
```

**FastMCP 4.0.x-native pattern:**
```python
@mcp.resource("anticafarmacia://health")
async def health() -> ResourceResult:
    """Static health/config view.
    
    FastMCP 4.0.x caches this on the client side.
    Mark immutable resources with cache metadata.
    """
    return ResourceResult(
        contents=[
            ResourceContent(
                json.dumps({"service": "AnticaFarmacia MCP", ...}),
                mime_type="application/json"
            )
        ],
        meta=ResourceMeta(
            cache_control="max-age=300",  # 5 min
            immutable=False
        )
    )
```

**Why this matters:**
- Client-side caching reduces server load
- Explicit MIME types + metadata enable richer clients
- Metadata drives cache invalidation strategy
- Resources are self-describing

### 2.3 **Prompts: Context-Sampled & Workflow-Aware**

**Old pattern (current):**
```python
@mcp.prompt()
def patient_intake(notes: str, tenant_id: str = "") -> str:
    """Build a structured patient-intake summary."""
    return f"You are assisting AnticaFarmacia intake...\n{notes}"
```

**FastMCP 4.0.x-native pattern:**
```python
@mcp.prompt()
async def patient_intake(notes: str, tenant_id: str = "", ctx: Context | None = None) -> list[PromptContent]:
    """Build a structured patient-intake summary.
    
    Samples client context if available:
    - Current tenant scope
    - User role/permissions
    - Recent patient history
    """
    # Resolve tenant from context or parameter
    tenant = await _resolve_tenant(ctx, tenant_id)
    
    # Sample ambient context: recent patient interactions, tenant policies
    ambient = await ctx.request_sampling(
        {
            "type": "recent_patients",
            "limit": 3,
            "tenant": tenant.id
        }
    ) if ctx else None
    
    # Build prompt with context
    base = (
        f"You are assisting {tenant.name} intake operations.\n"
        f"Recent patients: {ambient or 'none'}.\n"
        f"Input notes:\n{notes}"
    )
    
    return [
        TextPromptContent(text=base),
        PromptContent(type="policy", policy_rules=tenant.get_intake_rules())
    ]
```

**Why this matters:**
- Prompts become context-aware workflows
- Sample ambient state from client (recent history, user role)
- Tenant policies embedded in prompt context
- Workflow state can be tracked in EventStore

### 2.4 **Apps: Mostly Auto-Synthesized, Custom Where Needed**

**Old pattern (current):**
```python
# ferreromed_app.py has 500+ LOC hand-crafted PrefabApp
# manually building Card, Row, Column for each data table, form
```

**FastMCP 4.0.x-native pattern:**
```python
# FastMCP 4.0.x auto-generates tool UI from schema
# ui://prefab/tool/<hash>/renderer.html automatically created

# Custom app only for:
# 1. Complex workflows (multi-step form, conditional logic)
# 2. Rich visualization (maps, charts—use Embed component)
# 3. Tenant-specific branding

# Example: ferreromed maps app
@mcp.app()
async def ferreromed_maps_workflow(ctx: Context) -> PrefabApp:
    """Maps are complex → warrant custom app.
    
    But: reuse shared components from ui/components.py
    """
    tenant = await _resolve_tenant(ctx)
    locations = await _sample_map_locations(ctx)
    
    return PrefabApp(
        title=f"Maps - {tenant.name}",
        sections=[
            Card(
                title="Map",
                children=[
                    Embed(
                        url=f"/maps/embed/{_generate_token(locations)}",
                        height="600px"
                    )
                ]
            ),
            Card(
                title="Filters",
                children=_build_location_filters(tenant)
            )
        ]
    )
```

**Why this matters:**
- Most tools get free auto-generated UI
- Only build custom apps for workflows/visualization
- Reduces PrefabApp code by 80%+
- Consistent component library across MCPs

### 2.5 **Custom Routes: Keep Minimal, Let FastMCP Protocol Handle It**

**Old pattern (current):**
```python
@mcp.custom_route("/tiles/{z:int}/{x:int}/{y:int}.png", methods=["GET"])
async def tiles_png(z: int, x: int, y: int) -> Response:
    """Serve map tiles (binary PNG data)."""
    ...

@mcp.custom_route("/health", methods=["GET"])
async def health() -> dict:
    """Health check."""
    ...
```

**FastMCP 4.0.x-native pattern:**
```python
# Health/ready: FastMCP has built-in /health, /ready routes
# → Remove custom_route decorators; use FastMCP's defaults

# Binary/streaming endpoints: Keep as custom routes if truly needed
# → But prefer returning binary data as ResourceContent with MIME type

# Example: Instead of custom route, use resource + streaming
@mcp.resource("ferreromed://tiles/{z:int}/{x:int}/{y:int}")
async def tiles_resource(z: int, x: int, y: int) -> ResourceResult:
    """Serve map tiles as resource."""
    png_bytes = await _render_tile(z, x, y)
    return ResourceResult(
        contents=[
            ResourceContent(
                base64.b64encode(png_bytes).decode(),
                mime_type="image/png"
            )
        ]
    )
```

**Why this matters:**
- Fewer custom routes = simpler server
- FastMCP handles standard routes (health, discovery)
- Binary data via resources keeps protocol clean
- Monitoring/auth covers resources but not custom routes

---

## 3. Revised Enterprise Archetype (FastMCP 4.0.x-Aware)

### 3.1 **Three-Layer Architecture**

```
┌─────────────────────────────────────────────────────┐
│ FastMCP 4.0.x Server (Enterprise Master MCP)        │
├─────────────────────────────────────────────────────┤
│ Layer 1: Middleware (Policy, Auth, Error, Telemetry)│
│  - TenantResolutionMiddleware                       │
│  - AuthEnforcementMiddleware (DPoP, token refresh)  │
│  - ErrorNormalizationMiddleware (category, taxonomy)│
│  - RoutePolicy Middleware (tenant → capability map) │
│  - ObservabilityMiddleware (request-id, metrics)    │
├─────────────────────────────────────────────────────┤
│ Layer 2: Capability Registry & Routing Headers      │
│  - Tool/Resource/Prompt definitions (clean logic)   │
│  - Mcp-Name, Mcp-Param-* routing metadata in schema │
│  - Remote adapter decorators (proxy to downstream)  │
├─────────────────────────────────────────────────────┤
│ Layer 3: Downstream Adapters & EventStore           │
│  - Per-provider MCP adapters (auth, naming mapping) │
│  - EventStore for long-running workflows            │
│  - Circuit breaker + resilience per remote          │
└─────────────────────────────────────────────────────┘
```

### 3.2 **Middleware as Core Orchestration**

**Key middleware implementations:**

```python
class TenantResolutionMiddleware(Middleware):
    """Resolve tenant from request headers/auth/routing."""
    
    async def on_list_tools(self, ctx, call_next):
        tenant = await self._resolve_tenant(ctx)
        ctx.tenant = tenant  # Store for later use
        
        tools = await call_next(ctx)
        
        # Filter tools by tenant policy
        return [t for t in tools if self._allowed_by_policy(tenant, t)]
    
    async def on_call_tool(self, ctx, call_next):
        tenant = await self._resolve_tenant(ctx)
        tool_name = ctx.message.name
        
        # Check: is this capability allowed for this tenant?
        if not self._allowed_by_policy(tenant, tool_name):
            raise PermissionError(f"Tenant {tenant.id} not allowed tool {tool_name}")
        
        return await call_next(ctx)


class RouteDecisionMiddleware(Middleware):
    """Route tool to local or remote based on policy."""
    
    async def on_call_tool(self, ctx, call_next):
        tenant = await self._resolve_tenant(ctx)
        tool_name = ctx.message.name
        
        # Should this go to local or remote?
        route = self._policy_decide_route(tenant, tool_name)
        
        if route == "local":
            return await call_next(ctx)  # Local implementation
        else:
            # Remote: use remote adapter
            adapter = self._get_adapter(route.provider)
            return await adapter.call_tool(ctx)


class ErrorNormalizationMiddleware(Middleware):
    """Convert all errors to structured taxonomy."""
    
    async def on_call_tool(self, ctx, call_next):
        try:
            return await call_next(ctx)
        except Exception as e:
            # Map error to category, add structured response
            category = self._error_category(e)
            return CallToolResult(
                content=[TextContent(text=str(e))],
                isError=True,
                meta={
                    "error_category": category,
                    "error_code": self._error_code(e),
                    "recoverable": self._is_recoverable(e),
                    "tenant": ctx.tenant.id if hasattr(ctx, 'tenant') else None
                }
            )
```

### 3.3 **Capability Registry Aligned With FastMCP 4.0.x Routing**

```python
# capability/registry.py

@dataclass
class CapabilityContract:
    capability_id: str              # "patient.intake"
    tool_name: str                  # "local_patient_intake"
    version: str
    description: str
    input_schema: JsonSchema        # FastMCP schema
    output_schema: JsonSchema
    
    # FastMCP 4.0.x routing metadata
    mcp_method: str | None          # Auto-filled from tool_name pattern
    mcp_name: str | None            # Auto-filled from capability_id
    routing_hints: dict[str, str]   # Custom routing metadata
    
    # Enterprise contracts
    auth_profile: str               # "none" | "user" | "service"
    required_scopes: list[str]
    reliability_tier: str           # "tier_a" | "tier_b" | "tier_c"
    error_categories: list[str]     # Standard taxonomy
    pii_classification: str
    
    # FastMCP 4.0.x resource metadata
    cache_control: str | None       # For resources: "max-age=300"
    resource_stream: bool           # Can be streamed?
    
    @property
    def is_local(self) -> bool:
        return self.tool_name.startswith("local_")


# Example registry entry
CAPABILITIES = {
    "patient.intake": CapabilityContract(
        capability_id="patient.intake",
        tool_name="local_patient_intake",
        version="1.0",
        description="Build structured patient intake from free text",
        input_schema={"type": "object", "properties": {"notes": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"patient": {...}}},
        mcp_name="patient.intake",
        routing_hints={"domain": "patient", "operation": "intake"},
        auth_profile="user",
        required_scopes=["patient:read", "patient:write"],
        reliability_tier="tier_a",
        error_categories=["VALIDATION_ERROR", "AUTH_ERROR", "PROVIDER_ERROR"],
    ),
    "patient.search": CapabilityContract(
        capability_id="patient.search",
        tool_name="google_workspace.patients.search",  # Remote!
        version="1.0",
        ...,
        routing_hints={"domain": "patient", "provider": "google_workspace"},
        reliability_tier="tier_b",
    )
}
```

### 3.4 **Adapter Pattern for Remote MCPs (FastMCP-Native)**

```python
# adapters/google_workspace_adapter.py

class GoogleWorkspaceAdapter:
    """Adapts Google Workspace MCP to enterprise archetype.
    
    FastMCP 4.0.x: This adapter runs as a mounted remote MCP.
    Responsibility: auth attachment, error mapping, naming normalization.
    """
    
    def __init__(self, mcp: FastMCP, client: GoogleWorkspaceClient):
        self.mcp = mcp
        self.client = client
    
    async def mount_tools(self, registry: CapabilityRegistry):
        """Register each Google Workspace tool as a wrapper."""
        
        for capability_id, contract in registry.remote_capabilities("google_workspace"):
            tool_name = contract.tool_name
            provider_tool = contract.provider_tool_name
            
            @mcp.tool(name=tool_name)
            async def wrapped_tool(**kwargs) -> Any:
                # Normalize input (aliases, shape coercion)
                normalized = self._normalize_input(contract, kwargs)
                
                # Call remote
                result = await self.client.call_tool(provider_tool, normalized)
                
                # Normalize output + error category
                return self._normalize_output(contract, result)
```

### 3.5 **EventStore for Long Operations (FastMCP 4.0.x Built-In)**

```python
# For long-running operations: export PDF, generate report, batch upload

@mcp.tool()
async def export_patient_records_as_pdf(patient_id: str, ctx: Context | None = None) -> dict:
    """Export patient records as PDF (long operation).
    
    FastMCP 4.0.x EventStore tracks progress.
    Client can poll status via event subscription.
    """
    
    # Start async job, store in EventStore
    job_id = await _create_export_job(patient_id)
    
    # Return immediate result with event stream reference
    return {
        "job_id": job_id,
        "status": "queued",
        "event_stream": f"event://export/{job_id}",
        "estimate_seconds": 30
    }

# Separately, a tool to check status
@mcp.tool()
async def get_export_job_status(job_id: str) -> dict:
    """Poll status of long-running export job."""
    job = await _get_export_job(job_id)
    return {
        "job_id": job_id,
        "status": job.status,
        "progress_percent": job.progress,
        "result_url": job.result_url if job.status == "complete" else None
    }
```

---

## 4. Reorganized Folder Structure (FastMCP 4.0.x-Native)

```
<name>_mcp/
  server.py                      # FastMCP instance, middleware registration
  settings.py
  auth.py, oauth.py, rest_client.py
  
  middleware/
    tenant_resolution.py
    auth_enforcement.py
    route_decision.py
    error_normalization.py
    observability.py
  
  capability/
    registry.py                  # Canonical capability definitions
    contracts.py                 # CapabilityContract, validation
    error_taxonomy.py            # Standard error categories
  
  providers/
    local/
      tools.py                   # @mcp.tool() - clean implementations
      resources.py               # @mcp.resource() - with cache metadata
      prompts.py                 # @mcp.prompt() - with context sampling
    
    adapters/
      <provider_a>.py            # Mounted remote MCP adapter
      <provider_b>.py
  
  apps/
    components.py                # Shared PrefabUI components (small!)
    workflows/
      complex_workflow.py        # Only for true multi-step workflows
      maps.py                    # Only for visualization-heavy tasks
  
  observability/
    logging.py
    metrics.py
    audit.py
  
  tests/
    contract/
      test_capability_registry.py
      test_middleware_stacks.py
    adapters/
      test_google_workspace_adapter.py
    workflows/
      test_long_operations.py
  
  docs/
    CAPABILITIES.md
    OPERATIONS.md
    MIDDLEWARE_STACK.md
```

---

## 5. Key Differences: With vs. Without FastMCP 4.0.x as Core

| Concern | Without FastMCP 4.0.x Core | With FastMCP 4.0.x Core |
|---|---|---|
| **Tool Implementation** | Auth + error + retry logic inside each tool | Clean logic; middleware handles concerns |
| **Error Handling** | Exceptions → strings | Structured `CallToolResult` with metadata |
| **Resource MIME Types** | Implicit (JSON only) | Explicit MIME + cache metadata |
| **Prompts** | Static templates | Context-sampled, workflow-aware |
| **Routing** | Manual in tools or gateway layer | Automatic via Mcp-* headers + middleware policy |
| **UI Generation** | Hand-craft PrefabApp for each tool | 90% auto-synthesized; custom for workflows |
| **Auth/Policy** | Per-tool checks | Centralized middleware intercepts all calls |
| **Long Operations** | Manual polling, state management | FastMCP EventStore handles persistence |
| **Testing** | Tool-by-tool | Middleware stack + contract validation |
| **Horizontal Scale** | Sticky sessions risk | True stateless (FastMCP default) |

---

## 6. Migration Path (If You Adopt FastMCP 4.0.x-Native)

### Phase 1: Middleware Foundation (Week 1-2)
- Create `middleware/` folder structure
- Implement TenantResolutionMiddleware, AuthEnforcementMiddleware
- Register with FastMCP in `server.py`
- Move auth/error logic out of tools

### Phase 2: Capability Registry (Week 2-3)
- Create `capability/registry.py` with explicit contracts
- Add `mcp_name`, `routing_hints`, `cache_control` metadata
- Map all current tools/resources/prompts to contracts

### Phase 3: Tool Simplification (Week 3-4)
- Strip auth, error, retry logic from tool implementations
- Let middleware handle concerns
- Update tests to validate middleware stack, not tool internals

### Phase 4: Remote Adapters (Week 4-5)
- Reorganize `providers/adapters/` per remote MCP
- Each adapter mounts its tools via registry
- Add error category mapping per provider

### Phase 5: Apps & UI (Week 5-6)
- Create `apps/components.py` with shared UI library
- Remove 80% of ferreromed_app.py (auto-synthesis)
- Keep only complex workflows and visualizations

### Phase 6: EventStore for Long Ops (Week 6-7)
- Identify long-running tools (export, bulk update, report)
- Refactor as job + status queries
- Use FastMCP EventStore for progress tracking

### Phase 7: Testing & Validation (Week 7-8)
- Add contract tests (schema, error categories, auth profiles)
- Add middleware stack integration tests
- Add adapter smoke tests

---

## 7. Summary: FastMCP 4.0.x-Native Enterprise Archetype

With FastMCP 4.0.x as core, your enterprise MCP archetype becomes:

1. **Middleware-first** – Policy, auth, observability applied uniformly
2. **Contract-driven** – Capabilities defined in registry, not scattered
3. **Stateless by design** – Multi-worker, load-balanced, zero affinity
4. **Routing-aware** – Use Mcp-* headers for policy dispatch
5. **Auto-UI** – Most tools get free synthesized UI
6. **Cacheable** – Resources marked with cache metadata
7. **Event-sourced** – Long operations persist via EventStore
8. **Error-structured** – All errors normalized by middleware
9. **Adapter-based** – Remote MCPs plugged as adapters
10. **Simple** – Tool logic is business logic only; framework handles the rest

This is significantly simpler, more consistent, and more enterprise-grade than the current hand-crafted approach.

Should you want to implement this for anticafarmacia_mcp in 1.0.3, you'd have a working template to apply across all MCPs.
