# Skills Integration Reference

This document outlines the planned integration with external MCP servers and skills discovery patterns, with specific reference to [google_workspace_mcp v1.25.0](https://github.com/taylorwilsdon/google_workspace_mcp/releases/tag/v1.25.0) as a reference implementation for optimal skill packaging and introspection.

## Overview

AnticaFarmacia MCP can federate tools, resources, and prompts from remote MCP servers via the gateway architecture. Skills (packaged capabilities with metadata) are discovered and loaded through canonical artifact registrations.

## Reference: google_workspace_mcp v1.25.0

**Repository**: https://github.com/taylorwilsdon/google_workspace_mcp  
**Version**: v1.25.0  
**Reference URL**: https://github.com/taylorwilsdon/google_workspace_mcp/tree/v1.25.0

### v1.25.0 Highlights Relevant To AnticaFarmacia

- **Contacts v2 expansion**: richer multi-value contact fields and merge/replace/remove semantics in consolidated contact management tools.
- **Contacts groups consolidation**: grouped contact operations exposed through unified management flows.
- **Resiliency tests and retries**: improved transient-failure handling patterns (for example, retries on specific API conflict/network paths).
- **Scope/permissions model maturity**: granular permission levels and explicit scope hierarchy mappings that can be mirrored in gateway diagnostics.
- **Tiered tool loading maturity**: clearer tool-tier and service resolution patterns for capability filtering.

### Why This Reference?

- **Skills Packaging**: Demonstrates best practices for organizing AI-ready tools as reusable skills
- **Capability Metadata**: Includes schema validation, auth requirements, and error categorization
- **Tool Discovery**: Shows how capabilities are registered with rich metadata for downstream MCPs
- **Federated Routing**: Illustrates how remote skills integrate with local tool routing policies

### Key Patterns to Introspect

1. **Tool Organization** (`google_workspace_mcp/artifacts/tools/`)
   - Skills are organized by domain/source
   - Each skill includes JSON schema for inputs/outputs
   - Error categories and auth profiles defined per tool

2. **Resource Templates** (`google_workspace_mcp/artifacts/resources/`)
   - OpenAPI schemas and service discovery
   - Tenant and multi-workspace awareness
   - Resource URIs for client linking

3. **Capability Registry** (`google_workspace_mcp/capability/`)
   - Canonical capability contracts with versioning
   - Reliability tiers (tier_a, tier_b, tier_c)
   - PII classification for compliance
   - Integration with gateway routing

4. **Skills Metadata**
   - Reusable prompt templates tied to skill domains
   - Prefab UI apps for skill visualization
   - Tool dependencies and composition patterns

## Integration Strategy

### Phase 1: Remote Skills Discovery (Current)
- Gateway configuration enables federated tool resolution
- GOOGLE_WORKSPACE_MCP_URL points to remote skills server
- Tool route overrides allow local-preferred or remote-preferred execution

### Phase 2: Skills Cache & Validation (Future)
- Introspect remote MCP capability registries at startup
- Validate skill schemas for compatibility
- Cache skill metadata for fast lookup

### Phase 3: Skill Composition (Future)
- Combine local + remote skills for compound operations
- Track dependencies between skills (e.g., auth → tool execution)
- Support skill transformation middleware

### Phase 4: Skills as Artifacts (Roadmap)
- Sync remote skills into local artifact structure
- Version and diff skills across MCP updates
- Skill migration and backward-compatibility strategies

## Configuration for google_workspace_mcp

```bash
# Enable google_workspace_mcp as a remote backend
export ANTICAFARMACIA_GATEWAY_REMOTES_JSON='[
  {
    "name": "google-workspace-mcp",
    "namespace": "google_workspace_mcp",
    "type": "streamable-http",
    "url": "https://workspace.dchat.ditra.app/mcp",
    "auth": "YOUR_BEARER_TOKEN",
    "initTimeout": 20000,
    "timeout": 60000,
    "serverInstructions": true,
    "enabled": true
  }
]'

# Or use environment shortcuts
export GOOGLE_WORKSPACE_MCP_URL="https://workspace.dchat.ditra.app/mcp"
export GOOGLE_WORKSPACE_MCP_BEARER_TOKEN="YOUR_BEARER_TOKEN"
```

## Skill Introspection Checklist

When adding a new remote MCP to AnticaFarmacia, use this checklist:

- [ ] **Capability Registry**: Does the remote MCP expose `/capability/registry` or similar?
- [ ] **Tool Schemas**: Are input/output schemas JSON Schema compliant?
- [ ] **Auth Profile**: Is auth_profile set correctly (none, user, service, admin)?
- [ ] **Required Scopes**: Are scopes defined for gateway RBAC?
- [ ] **Error Categories**: Are error_categories defined for fault handling?
- [ ] **Reliability Tier**: Is reliability_tier set (tier_a, tier_b, tier_c)?
- [ ] **PII Classification**: Is pii_classification declared (low, medium, high)?
- [ ] **Resource URIs**: Are resources uniquely addressable (e.g., gs://workspace/...)?
- [ ] **Tenant Awareness**: Does the MCP support multi-tenant contexts?
- [ ] **Tool Dependencies**: Are tool dependencies explicitly declared?

## Future: Skills Store

Once the skills discovery phase matures, AnticaFarmacia will support:

1. **Skill Registry Publishing**: Export local skills as a registry for other MCPs
2. **Skill Marketplace**: Centralized registry of vetted, reusable skills
3. **Version Management**: Skill versioning and migration guides
4. **Compliance Validation**: Automated PII/compliance checks before deployment
5. **Metrics & Observability**: Skill usage, latency, and error tracking

## Implementation Resources

See these documents for detailed implementation guidance:

1. **[SKILL_FEDERATION.md](SKILL_FEDERATION.md)** - Complete architecture and patterns
2. **[SKILL_FEDERATION_EXAMPLES.md](SKILL_FEDERATION_EXAMPLES.md)** - Concrete code examples
3. **[SKILL_FEDERATION_QUICKSTART.md](SKILL_FEDERATION_QUICKSTART.md)** - 5-step setup guide

## Code Modules

- `artifacts/skill_federation.py` - Core discovery, normalization, routing
- `artifacts/skill_federation_integration.py` - Server startup integration
- `artifacts/skill_normalizers/` - Domain-specific normalizers (google_workspace, etc.)

## References

- FastMCP 4.0.x Capability Model: `/docs/FastMCP-capabilities.md`
- Artifact-First Architecture: `README.md`
- Gateway Routing Policy: `servers/anticafarmacia_mcp/gateway/README.md`
- OAuth 2.1 + GCIP Integration: `.env_example` (Sections 2-4)
- google_workspace_mcp v1.25.0: https://github.com/taylorwilsdon/google_workspace_mcp/tree/v1.25.0
