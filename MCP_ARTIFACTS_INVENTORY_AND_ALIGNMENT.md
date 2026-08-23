# MCP Artifacts Inventory & Architecture Analysis
## Current State, Organization, and MCP 2.x Alignment

---

## 1. Current MCP Artifacts Across Your Workspace

### 1.1 **Tools** (@mcp.tool() decorators)
Function-based, schema-driven capabilities with input/output.

**Patterns observed:**
- Local tools (diagnostics, auth, gateway health, API pass-throughs)
- Remote/gateway tools (proxied to downstream MCPs)
- Utility tools (health, status, policy evaluation)

**Example distribution (anticafarmacia_mcp):**
- `local_auth_debug`: inspect auth headers
- `local_gateway_summary`: gateway configuration
- `local_api_get`, `local_api_post`: REST pass-through
- `gateway_remote_auth_status`: remote token diagnostics
- `gateway_remote_auth_recover`: recovery actions
- ~15 remote proxied tools (namespaced by provider)

**Scale across workspace:**
- ferreromed_mcp: ~35+ tools (patients, orders, quotations, ASLs, trips, inventory, maps)
- anticafarmacia_mcp: ~12 local + dynamic remote proxies
- ditrasoftware_template_mcp: ~6 (template/stub pattern)

### 1.2 **Resources** (@mcp.resource() decorators)
Static or async-fetched content with URIs.

**Patterns observed:**
- Config snapshots (`anticafarmacia://health`, `anticafarmacia://security/profile`)
- Gateway metadata (`anticafarmacia://gateway/remotes`)
- API metadata (`ferreromed://openapi.yaml`)
- UI prefab synthesis resources (FastMCP auto-generates `ui://prefab/tool/<hash>/renderer.html`)

**Resource URI schemes in use:**
- `anticafarmacia://` - domain-specific
- `ferreromed://` - domain-specific
- `ui://` - FastMCP synthesized (tool/resource UI renderers)
- No standard use of `resource://` or other generic schemes

**Content types:**
- JSON (configs, metadata)
- YAML (OpenAPI)
- HTML (synthesized UI renderers)
- String (health status, text data)
- No binary/blob resources currently exposed

### 1.3 **Prompts** (@mcp.prompt() decorators)
Parameterized prompt templates for AI guidance.

**Patterns observed:**
- Workflow guidance (e.g., "how to triage a patient", "how to plan an order")
- AI-facing instructions (structured task templates)
- Named, parameter-driven (not inline)

**Examples:**
- anticafarmacia: 3 prompts (patient intake, order planning, gateway route review)
- ferreromed: 8+ prompts (patient triage, order creation, quotation decision, ASL lookup, data quality, maps)

**Current organization:**
- Centralized in `providers/local_prompts.py`
- Registered at startup
- No prompt context sampling or dynamic prompt generation

### 1.4 **Apps** (PrefabApp providers for UI rendering)
Interactive, visual user interfaces for complex tasks.

**Patterns observed:**
- ferreromed_mcp: has `apps/ferreromed_app.py` with PrefabApp-based UI (components: Card, Row, Column, Heading, Badge, DataTable, Embed, Muted)
- Maps visualization: `maps.py` provides interactive map rendering with caching, tile generation, embed tokens

**Current implementation:**
- Registered via `create_local_app_providers()` → passed to `FastMCP(providers=[...])`
- PrefabUI components for structured layout
- HTML/canvas-based rendering
- Cache management for embeds and tile rendering

### 1.5 **Custom Routes** (@mcp.custom_route())
Raw HTTP endpoints outside the MCP protocol.

**Patterns observed:**
- Health/readiness checks: `/health`, `/ready`
- Maps tile service: `/tiles/{z:int}/{x:int}/{y:int}.png`
- Maps embed endpoint: `/maps/embed/{token:str}.html`
- Maps tile base64: `/maps/tile/{z:int}/{x:int}/{y:int}.b64`

**Purpose:**
- Non-MCP HTTP consumers (orchestration, health probes)
- Streaming/binary content (PNG tiles)
- Legacy API compatibility

### 1.6 **Middleware & Context Injection**
Advanced FastMCP features for request/response interception.

**Patterns observed:**
- `_StripToolHashMiddleware`: rewrites hashed tool names for Prefab UI compatibility
- Request ID propagation (not yet fully implemented)
- iOS Safari tap-fix CSS/JS injection
- Context-aware client detection (ChatGPT vs Claude vs other)

**Current hooks:**
- `on_list_tools`: modify tool metadata
- `on_call_tool`: modify tool invocations
- `on_read_resource`: modify resource content
- Auth middleware: DPoP toggle, token refresh logic

---

## 2. How Artifacts Are Currently Organized & Wrapped

### 2.1 **Repository Structure**
Every MCP follows this layout:

```
<name>_mcp/
  server.py                    # FastMCP instance creation, main entry
  settings.py                  # Config/env parsing
  auth.py                       # Auth provider setup
  oauth.py                     # OIDC/OAuth configuration
  rest_client.py               # HTTP client for downstream APIs
  maps.py                      # (ferreromed only) map rendering
  providers/
    __init__.py                # Export registration functions
    local_tools.py             # @mcp.tool() definitions
    local_resources.py         # @mcp.resource() definitions
    local_prompts.py           # @mcp.prompt() definitions
    local_apps.py              # PrefabApp provider creation
  gateway/
    __init__.py                # exports
    direct.py                  # direct downstream tool calls
    proxy.py                   # proxy mount setup
    remote_auth.py             # auth refresh + runtime token store
  apps/
    <name>_app.py              # PrefabApp implementation
  resources/
    openapi.py                 # (ferreromed) OpenAPI resource
  prompts/
    templates.py               # (ferreromed) prompt templates (alt naming)
  tools/
    (not consistently used; logic in providers/local_tools.py)
```

### 2.2 **Artifact Registration Pattern**

**At startup (server.py):**
1. Create FastMCP instance
2. Pass auth provider and app providers
3. Call registration functions:
   - `register_local_tools(mcp, ...)`
   - `register_local_resources(mcp, ...)`
   - `register_local_prompts(mcp)`
   - `register_maps(mcp)` (ferreromed)
4. Mount remote MCPs via `mount_remote_proxies(mcp, ...)`
5. Add middleware (context rewriting, hash stripping, etc.)

**Wrapping strategy:**
- Tools: wrapped with auth resolution, error handling, context injection
- Resources: wrapped with fetch caching, error recovery
- Prompts: static templates (no runtime wrapping)
- Apps: custom PrefabApp instances with domain-specific UI logic
- Remote MCPs: namespaced tool/resource proxies with resilience

### 2.3 **Cross-Cutting Patterns**

**Auth wrapping:**
- Every tool can accept optional `access_token`, `api_key`, or `refresh_token` as parameters
- Context-injected auth merged with parameter-supplied auth
- Header-based auth resolution (`Authorization: Bearer ...`, `X-Api-Key`, `X-Refresh-Token`)

**Resilience wrapping:**
- Remote tool calls wrapped with:
  - Circuit breaker per remote
  - Timeout enforcement (separate list/call timeouts)
  - Retry with exponential backoff
  - Degraded-mode fallback

**Error wrapping:**
- Errors normalized into categories: `VALIDATION_ERROR`, `AUTH_ERROR`, `PROVIDER_ERROR`, `TRANSIENT_ERROR`
- Optional error detail masking for production

---

## 3. MCP 2.x Specification Capabilities (and What You're Using/Missing)

### 3.1 **Core Artifacts (Implemented)**
- ✅ **Tools**: Full support. You use standard tool definitions with schemas, inputs, outputs.
- ✅ **Resources**: Full support. You expose static/dynamic resources via URIs. No sampling or pagination yet.
- ✅ **Prompts**: Full support. You have parameterized prompts. No prompt context sampling yet.

### 3.2 **Advanced Content Types (Not Yet Used)**
- ❌ **Rich text resources**: Tools/resources return structured content types
  - `TextContent` - plain text blocks
  - `ImageContent` - images (MIME type + base64 or URL)
  - `EmbeddedResource` - nested resource links
  - `BlobResourceContents` - binary data (base64)
  - **Gap**: Your resources/tools return simple JSON/string; no rich type encoding

- ❌ **Tool I/O progressive execution**:
  - MCP 2.x allows tools to return `isError: true` with structured error details
  - Allows incremental results or async progress
  - **Gap**: Current tools return atomic success/failure

### 3.3 **Sampling Context (Not Yet Used)**
- ❌ **Prompt Sampling**: Tools can request client-side context (user's current screen, clipboard, selection)
  - `SamplingMessage`: bidirectional message for requesting ambient context
  - **Use case**: "give me the current code block the user is looking at" → pass to AI
  - **Gap**: Your prompts are static; no ambient context requests

### 3.4 **Resource Pagination & Listing**
- ⚠️ **Partial**: FastMCP supports `list_resources()` and resource pagination via `list_page_size`
  - **Gap**: You don't expose a `list_resources` endpoint for clients to discover resources by URI pattern

### 3.5 **Tool Progressive Results**
- ❌ **MCP 2.x allows**:
  - Tools return `isError` field explicitly
  - Tools return `result` arrays (multiple result blocks)
  - Tools can return `CallToolResult` with structured success/failure
  - **Gap**: Your tools either succeed (return data) or raise exceptions; no explicit error objects

### 3.6 **Root-level well-known routes**
- ✅ **Implemented** (FastMCP default):
  - `/.well-known/mcp.json` - capability discovery
  - OAuth discovery at standard locations
  - Follows MCP 2.x spec for server discovery

### 3.7 **Stateless HTTP Scale**
- ✅ **Ready**: Your servers are stateless; can run multiple workers behind load balancer
- ✅ **FastMCP 4.0.x default**: HTTP-based with optional SSE fallback

### 3.8 **Modern Protocol Era**
- ✅ **Supported by FastMCP**: Modern protocol (4.0.x) vs legacy negotiation
  - Routing headers: `Mcp-Method`, `Mcp-Name`, `Mcp-Param-*`
  - Client auto-negotiation
  - **Gap**: You don't explicitly leverage routing headers for tenant/policy dispatch

### 3.9 **Extensions & Custom Protocol Features**
- ❌ **Not used**: MCP allows custom extensions for:
  - Custom request/response wrappers
  - Server-side hints and metadata
  - Capability negotiation
  - **Gap**: No custom extension definitions

---

## 4. Artifact Inventory by Server

### 4.1 **anticafarmacia_mcp** (Master MCP)
| Artifact Type | Count | Examples |
|---|---|---|
| Local Tools | 12 | local_auth_debug, local_gateway_summary, local_api_get/post, gateway_remote_auth_* |
| Remote Proxied Tools | dynamic | Namespaced by provider (e.g., `google_workspace.gmail.search`) |
| Resources | 3 | anticafarmacia://health, security/profile, gateway/remotes |
| Prompts | 3 | patient_intake, order_planner, gateway_route_review |
| Apps | 1 | AnticaFarmacia (PrefabApp) |
| Custom Routes | 2 | /health, /ready |

### 4.2 **ferreromed_mcp** (Domain MCP)
| Artifact Type | Count | Examples |
|---|---|---|
| Local Tools | 35+ | patients_list, patients_get, orders_create, quotations_accept, trips_list, inventory_search, maps_* |
| Resources | 3 | ferreromed://openapi.yaml, ferreromed://health, (synthesized UI resources) |
| Prompts | 8 | patient_triage, create_order_from_notes, quotation_decision, asl_lookup_helper, maps_gather_and_map |
| Apps | 1 | FerreroMed (PrefabApp with maps, data tables) |
| Custom Routes | 4 | /tiles/{z}/{x}/{y}.png, /maps/embed/{token}.html, /maps/tile/{z}/{x}/{y}.b64, /health, /ready |

### 4.3 **Template MCPs** (ditrasoftware, ditrasoftware_template, lottomaticapss, ditra_devtest)
| Artifact Type | Count | Status |
|---|---|---|
| Local Tools | 4 (stubbed) | Template only; not activated |
| Resources | 2 (stubbed) | Template only |
| Prompts | 0 (commented out) | Template scaffold |
| Apps | 1 (stubbed) | Placeholder |

---

## 5. Organizational Gaps & Simplification Opportunities

### 5.1 **Inconsistent Naming & URI Scheme**
**Current:**
- anticafarmacia:// resources
- ferreromed:// resources
- ui:// (FastMCP synthesized)
- No standard pattern

**Opportunity:**
- Adopt domain-first capability IDs (from ENTERPRISE_MCP_ARCHETYPE):
  - `domain.service.resource.operation` → `anticafarmacia.health.status`
  - `domain.service.resource.schema` → `anticafarmacia.schema.security-profile`
- Use consistent URI schemes: `domain://<type>/<path>`

### 5.2 **No Resource Pagination or Discovery**
**Current:**
- Resources are fixed at registration time
- No `list_resources()` endpoint
- No pagination for large result sets

**Opportunity:**
- Implement `list_resources(cursor, limit)` for dynamic discovery
- Support cursor-based pagination for large datasets
- Allow pattern matching on resource URIs (e.g., `/anticafarmacia/*`)

### 5.3 **Tools Don't Use Structured Error Responses**
**Current:**
- Tools raise exceptions; framework converts to error strings

**Opportunity:**
- Adopt MCP 2.x `CallToolResult` with structured errors:
  ```python
  CallToolResult(
    content=[TextContent(text="...")],
    isError=True,  # explicit error flag
    error={
      "category": "VALIDATION_ERROR",
      "code": "INVALID_DATE",
      "message": "Date must be YYYY-MM-DD"
    }
  )
  ```

### 5.4 **Apps Have No Shared Component Library**
**Current:**
- ferreromed_mcp has PrefabApp UI (Card, Row, Column, DataTable, etc.)
- No standardized component reuse across servers

**Opportunity:**
- Create shared `ui_components/` library for consistent UI across all MCPs
- Standardize data table, form, card, workflow step components
- Reduce duplication in ferreromed and future MCPs

### 5.5 **Prompts Are Not Sampled or Context-Aware**
**Current:**
- Static prompt templates
- No request for client ambient context (screen, clipboard, selection)

**Opportunity:**
- Use MCP 2.x sampling to request context:
  - Current user, tenant, screen, code block
  - Client state or preferences
- Dynamically generate prompts based on context

### 5.6 **Remote Tool Namespace Needs Standardization**
**Current:**
- Naming convention unclear and inconsistent
- Example: `google_workspace.gmail.search` vs `namespace.tool_name`

**Opportunity:**
- Adopt strict capability-first naming:
  - Local: `local.<category>.<tool>` (e.g., `local.auth.debug`)
  - Remote: `<provider>.<domain>.<capability>` (e.g., `google_workspace.gmail.search`)
  - Aliased: Accept both forms for backward compatibility

### 5.7 **No Explicit Capability Contract Registry**
**Current:**
- Capabilities live spread across tools, resources, prompts
- No single canonical source of capability schema and metadata

**Opportunity:**
- Create `capability/registry.py` for all MCPs:
  ```python
  CAPABILITIES = {
    "local.auth.debug": CapabilityContract(
      capability_id="local.auth.debug",
      tool_name="local_auth_debug",
      version="1.0",
      schema=...,
      error_categories=[...],
      auth_profile="none",
      reliability_tier="tier_a"
    ),
    ...
  }
  ```

### 5.8 **No Resource Type or Content Encoding Standard**
**Current:**
- Resources return strings/JSON
- No explicit content-type or MIME metadata

**Opportunity:**
- Enforce MCP 2.x resource format:
  ```python
  ResourceResult(
    contents=[
      ResourceContent(
        content="...",  # or base64 for binary
        mime_type="application/json",
        meta={"encoding": "utf-8", "charset": "utf-8"}
      )
    ]
  )
  ```

---

## 6. Recommended Organization Model (for 1.0.3+)

### 6.1 **Unified Folder Template**
```
<name>_mcp/
  server.py                      # FastMCP creation
  settings.py                    # Config
  auth.py, oauth.py, rest_client.py
  
  capability/
    registry.py                  # All contract definitions
    contracts.py                 # CapabilityContract dataclass
    discovery.py                 # list_resources(), introspection
    error_taxonomy.py            # Shared error categories
    
  providers/
    local_tools.py               # @mcp.tool()
    local_resources.py           # @mcp.resource()
    local_prompts.py             # @mcp.prompt()
    local_apps.py                # PrefabApp creation
    
  adapters/
    (if master MCP)
    downstream_<provider>.py     # Per-provider adapter
    
  tools/
    (organized by domain)
    auth_tools.py
    gateway_tools.py
    business_tools.py
    
  resources/
    (organized by domain)
    config_resources.py
    schema_resources.py
    
  ui/
    components.py                # Shared PrefabApp components
    app.py                        # App entry point
    
  gateway/
    (if master/aggregator)
    direct.py, proxy.py, remote_auth.py
    
  observability/
    logging.py, metrics.py, audit.py
    
  tests/
    contract/
      test_tool_contracts.py
      test_resource_contracts.py
    adapters/
      test_remote_providers.py
    
  docs/
    ARCHITECTURE.md
    CAPABILITIES.md
    OPERATIONS.md
```

### 6.2 **Artifact Registration at Startup**
```python
def create_mcp() -> FastMCP:
    # 1. Load capabilities from registry
    capabilities = load_capability_registry()
    
    # 2. Create FastMCP with config
    mcp = FastMCP(
        "MCP Name",
        providers=[create_app_providers()],
        auth=create_auth_provider()
    )
    
    # 3. Register providers (tools, resources, prompts)
    register_local_tools(mcp, capabilities)
    register_local_resources(mcp, capabilities)
    register_local_prompts(mcp, capabilities)
    
    # 4. Register remote adapters (if master MCP)
    for adapter in downstream_adapters:
        mount_adapter(mcp, adapter, capabilities)
    
    # 5. Add middleware
    mcp.add_middleware(...)
    
    return mcp
```

### 6.3 **Capability Contract Standard**
```python
@dataclass
class CapabilityContract:
    capability_id: str
    display_name: str
    role: str  # "local" | "remote:<provider>" | "composite"
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    aliases: dict[str, str]  # param name mappings
    error_categories: list[str]
    error_mapping: dict[str, str]  # provider error -> category
    auth_profile: str
    reliability_tier: str  # "tier_a" | "tier_b" | "tier_c"
    fallback_mode: str  # "none" | "local_alternative" | "cached"
    pii_classification: str  # "none" | "low" | "high"
    required_scopes: list[str]
    examples: list[dict[str, Any]]
```

---

## 7. How to Apply This to Your Workspace

### Phase 1: Inventory & Document (week 1)
- [ ] For each MCP, create `CAPABILITIES.md` listing all capabilities
- [ ] Extract capability contracts into `capability/registry.py` for each
- [ ] Map remote providers to adapter modules

### Phase 2: Normalize Organization (week 2-3)
- [ ] Rename/reorganize folders to match unified template
- [ ] Move tool/resource/prompt definitions to organized submodules
- [ ] Create `capability/contracts.py` and `capability/discovery.py`

### Phase 3: Implement Structured Errors & Content (week 3-4)
- [ ] Adopt MCP 2.x `CallToolResult` with structured errors
- [ ] Implement `ResourceContent` with explicit MIME types
- [ ] Add capability schema introspection tool

### Phase 4: Add Master MCP Orchestration (week 4-5)
- [ ] Implement master capability registry aggregation
- [ ] Add policy-driven tool routing
- [ ] Implement tenant-scoped capability policies

### Phase 5: Governance & Testing (week 6+)
- [ ] Add contract tests for all adapters
- [ ] Implement onboarding gate (template compliance, lint, smoke tests)
- [ ] Create CI/CD checks for capability consistency

---

## 8. Summary Table: Current vs. Target State

| Aspect | Current | Target (1.0.3+) |
|---|---|---|
| **Naming** | Domain-specific (`anticafarmacia://`, `ferreromed://`) | Canonical capability IDs, consistent schemes |
| **Organization** | Scattered across providers, server.py | Unified template with capability registry |
| **Contracts** | Implicit in tool/resource definitions | Explicit in `capability/registry.py` |
| **Errors** | Exceptions → strings | Structured `CallToolResult` with categories |
| **Resource Discovery** | Fixed at runtime | Dynamic `list_resources()` with pagination |
| **Prompts** | Static templates | Sampled context-aware templates |
| **Apps/UI** | Embedded in ferreromed | Shared component library across MCPs |
| **Governance** | Ad-hoc | Onboarding gate with quality checks |
| **Testing** | Manual | Automated contract + smoke tests |

---

This inventory and blueprint should guide your simplification and make every MCP consistent, intuitive, and enterprise-grade.
