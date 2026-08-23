# FastMCP 4.0.x Enterprise MCP Implementation Guide

## Overview

You now have a complete scaffold for building enterprise-grade MCPs:

1. **ditra_devtest_mcp** - Living reference implementation with full middleware & capability registry
2. **ditrasoftware_template_mcp** - Clean scaffold for starting new MCPs
3. **Architecture documentation** - ENTERPRISE_MCP_ARCHETYPE_SIMPLIFIED.md, FASTMCP_4_0_X_AS_CORE_ARCHITECTURE.md, MCP_ARTIFACTS_INVENTORY_AND_ALIGNMENT.md

---

## Quick Reference

### For Testing Enterprise Architecture

**Use `ditra_devtest_mcp`:**
- Has complete middleware stack (TenantResolution → Auth → ErrorNormalization → Observability)
- Has capability registry with example contracts
- Has base adapter classes for remote MCPs
- Ready to add adapters for anticafarmacia_mcp, ferreromed_mcp, lottomaticapss_mcp
- Can serve as master MCP testing harness

```bash
cd servers/ditra_devtest_mcp
python -m pytest tests/  # Once you add tests
```

### For Creating a New MCP

**Use `ditrasoftware_template_mcp` as scaffold:**
1. Copy the folder: `cp -r ditrasoftware_template_mcp/ my_new_mcp/`
2. Update names in files (find/replace `ditrasoftware_template_mcp` → `my_new_mcp`)
3. Follow TEMPLATE_GUIDE.md in that folder
4. Customize:
   - `capability/registry.py` - Your capabilities
   - `artifacts/tools/local.py` - Your tools
   - `providers/adapters/` - Adapters for remote MCPs
   - `middleware/` - Custom tenant/auth logic

---

## Implementation Roadmap

### Phase 1: Establish ditra_devtest_mcp as Test Harness (This Week)

**Goal:** Validate enterprise architecture with multiple remote MCPs

**Tasks:**
- [ ] Add adapters in `providers/adapters/`:
  - `anticafarmacia.py` - Wrap anticafarmacia_mcp tools
  - `ferreromed.py` - Wrap ferreromed_mcp tools
  - `lottomatica.py` - Wrap lottomaticapss_mcp tools
- [ ] Update `capability/registry.py` with:
  - Local diagnostic tools
  - Remote tools from adapters (name-mapped)
- [ ] Implement adapter concrete subclasses (actual HTTP calls to remotes)
- [ ] Add smoke tests to validate middleware stack
- [ ] Document adapter patterns

**Result:** ditra_devtest_mcp becomes working test environment for enterprise patterns

### Phase 2: Create Adapter Framework (Week 2)

**Goal:** Make adapters reusable pattern for any remote MCP

**Tasks:**
- [ ] Enhance `providers/adapters/base.py` with:
  - HTTP client utilities
  - Auth attachment patterns (bearer, api-key, etc.)
  - Resilience (retry, timeout, circuit-break)
  - Error mapping strategies
- [ ] Create `providers/adapters/http_client.py` - Shared HTTP transport
- [ ] Document adapter best practices

**Result:** Clear, repeatable pattern for connecting remote MCPs

### Phase 3: Enhance Capability Registry (Week 2-3)

**Goal:** Make registry source of truth for all capabilities

**Tasks:**
- [ ] Add dynamic capability loading from adapters
- [ ] Add `get_capabilities_by_provider()`, filtering methods
- [ ] Add introspection tool: `gateway_discover_capabilities()`
- [ ] Add schema validation tool: `gateway_validate_capability_input()`

**Result:** Clients can discover and validate all capabilities

### Phase 4: Add EventStore for Long Operations (Week 3)

**Goal:** Support long-running operations (export, bulk update, report generation)

**Tasks:**
- [ ] Create `observability/event_store.py` - Simple in-memory EventStore
- [ ] Refactor long-operation tools as:
  - Tool 1: `start_<operation>()` → returns job_id + event_stream
  - Tool 2: `get_<operation>_status(job_id)` → returns progress, result
- [ ] Example: `export_patient_records()` → `get_export_status(job_id)`

**Result:** Long operations persist progress across client reconnects

### Phase 5: Apply to anticafarmacia_mcp (Week 4)

**Goal:** Migrate main MCP to enterprise architecture (non-disruptive)

**Tasks:**
- [ ] Add middleware to anticafarmacia_mcp/server.py
- [ ] Add capability/registry.py
- [ ] Refactor tools to be clean business logic (middleware handles auth/errors)
- [ ] Add provider/adapters/ for downstream dependencies
- [ ] Add comprehensive tests

**Result:** anticafarmacia_mcp becomes production-ready enterprise implementation

### Phase 6: Simplify ditrasoftware_template_mcp (Week 4-5)

**Goal:** Ensure template is minimal, clear, customizable

**Tasks:**
- [ ] Review template for clarity
- [ ] Ensure all TODOs are actionable
- [ ] Add example implementation sections
- [ ] Create quick-start video walkthrough (optional)

**Result:** Templates are ready for new teams to build MCPs quickly

### Phase 7: Documentation & Training (Week 5)

**Goal:** Make enterprise MCP pattern teachable

**Tasks:**
- [ ] Create "Architecture Decision Record" (ADR) explaining middleware-first pattern
- [ ] Create adapter implementation guide with examples
- [ ] Add capability contract best practices
- [ ] Document error taxonomy extension process
- [ ] Create troubleshooting guide

**Result:** Teams understand why and how to use enterprise patterns

---

## Key Files & Their Purpose

### ditra_devtest_mcp (Reference Implementation)

| Path | Purpose |
|---|---|
| `middleware/` | Enterprise middleware stack (finalized) |
| `capability/registry.py` | Example capability definitions |
| `providers/adapters/base.py` | Base class for remote MCP adapters |
| `server.py` | FastMCP setup with middleware registration |

### ditrasoftware_template_mcp (Scaffold)

| Path | Purpose |
|---|---|
| `TEMPLATE_GUIDE.md` | How to use this template |
| `middleware/` | Enterprise middleware (TODO comments for customization) |
| `capability/registry.py` | Empty; replace with your capabilities |
| `providers/adapters/` | Scaffold; create adapters here |
| `artifacts/` | Implement your tools/resources/prompts |
| `server.py` | Pre-configured with middleware; ready to use |

### Architecture Documentation

| Document | Content |
|---|---|
| `ENTERPRISE_MCP_ARCHETYPE_SIMPLIFIED.md` | 3-plane model, unified template, onboarding gate |
| `FASTMCP_4_0_X_AS_CORE_ARCHITECTURE.md` | How FastMCP 4.0.x reshapes artifact patterns |
| `MCP_ARTIFACTS_INVENTORY_AND_ALIGNMENT.md` | Current state analysis + gaps |
| `MCP_ARTIFACTS_INVENTORY_AND_ALIGNMENT.md` | How FastMCP 4.0.x reshapes artifact patterns |

---

## Testing Strategy

### Unit Tests
```bash
# Test middleware stack isolation
tests/middleware/test_tenant_resolution.py
tests/middleware/test_auth_enforcement.py
tests/middleware/test_error_normalization.py

# Test capability registry
tests/capability/test_registry.py
tests/capability/test_contracts.py
```

### Integration Tests
```bash
# Test middleware stack together
tests/integration/test_middleware_stack.py

# Test adapter pattern
tests/adapters/test_remote_mcp_adapter.py
```

### Smoke Tests
```bash
# Start MCP, call sample tools, verify responses
./smoke_tests/test_enterprise_mcp.sh
```

---

## Migration Path for Existing MCPs

### For anticafarmacia_mcp (Priority 1)

1. Add middleware/ and capability/ folders
2. Move auth/error logic from tools to middleware
3. Create capability registry from existing tools
4. Test non-disruptively (feature flag for new middleware)
5. Gradual rollout to production

### For ferreromed_mcp (Priority 2)

1. Same as anticafarmacia_mcp
2. Plus: Simplify PrefabApp code (rely on auto-synthesis)

### For lottomaticapss_mcp (Priority 3)

1. Start with ditrasoftware_template_mcp scaffold
2. Customize for domain
3. Connect to master MCP as adapter

---

## Success Criteria

✅ **ditra_devtest_mcp** can orchestrate anticafarmacia_mcp, ferreromed_mcp, lottomaticapss_mcp as remote adapters  
✅ All errors normalized to standard taxonomy  
✅ Tenant routing works across local and remote tools  
✅ Middleware stack tested in isolation and together  
✅ ditrasoftware_template_mcp scaffold used to create new MCP without friction  
✅ Long operations persisted in EventStore  
✅ Resource caching metadata enforced  
✅ Context-sampled prompts framework ready (not yet implemented in tools)  

---

## Next Action

1. **Start Phase 1:** Create adapters in `ditra_devtest_mcp/providers/adapters/`
2. **Test:** Run middleware stack against sample tool calls
3. **Document:** Record what you learn about adapter patterns
4. **Iterate:** Refine template based on what works

---

## Questions?

Refer to:
- `TEMPLATE_GUIDE.md` in ditrasoftware_template_mcp (how to start new MCP)
- `FASTMCP_4_0_X_AS_CORE_ARCHITECTURE.md` (why this architecture)
- `ENTERPRISE_MCP_ARCHETYPE_SIMPLIFIED.md` (overall strategy)
