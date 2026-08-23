# FastMCP 4.0.x Guidance for Enterprise Master MCP Architecture

## Purpose
This document maps FastMCP 4.0.x capabilities and best practices to a master MCP pattern (example: anticafarmacia_mcp) that governs downstream MCP dependencies for a customer tenant.

---

## 1. Strategic Positioning
A tenant-facing master MCP should operate as:
- Policy and governance control plane
- Contract normalization layer
- Resilience and observability boundary
- Secure router for downstream MCP capabilities

FastMCP 4.0.x provides primitives to implement this cleanly without replacing existing architecture.

---

## 2. FastMCP 4.0.x Features to Exploit

### 2.1 Modern protocol negotiation
- Client mode auto negotiates modern era when supported.
- Use this to support mixed legacy and modern downstream fleets.
- Benefit: safer interoperability while upgrading providers progressively.

### 2.2 Stateless HTTP for horizontal scale
- FastMCP explicitly recommends stateless mode for multi-instance deployments.
- This avoids sticky-session failures behind load balancers.
- Master MCP should remain stateless by default in production.

### 2.3 Host and Origin protection
- Enable host/origin request guard for internet-facing endpoints.
- Add explicit allowed hosts and allowed origins when behind reverse proxy.
- Benefit: DNS rebinding and origin abuse resistance.

### 2.4 Gateway routing headers
- FastMCP supports routing headers in modern protocol:
  - Mcp-Method
  - Mcp-Name
  - Mcp-Param-*
- Use x-mcp-header annotations to route requests by tenant/capability without parsing full JSON bodies.
- Benefit: efficient tenant-aware gateway dispatch and policy control.

### 2.5 OAuth mounting correctness
- For mounted authenticated servers, discovery routes must remain root-level.
- Preserve invariant: base_url + mcp_path = externally reachable MCP URL.
- Benefit: standards-compliant OAuth discovery and fewer client auth failures.

### 2.6 EventStore for long-running operations
- For long jobs and SSE resilience, use EventStore and SSE polling patterns.
- Benefit: progress continuity across proxy/lb connection resets.

### 2.7 Explicit middleware composition
- FastMCP supports Starlette middleware integration.
- Use this to centralize request-id, tenant resolution, policy checks, telemetry, and error normalization.

### 2.8 Custom routes caveat
- FastMCP custom routes are operationally useful, but not protected by AuthProvider by design.
- Keep /health and /ready there, but do not expose sensitive admin actions via unauthenticated custom routes.

### 2.9 Client-side response caching (modern)
- For controllers and internal orchestrators using FastMCP Client, enable modern response caching for list operations.
- Benefit: lower control-plane latency and less discovery overhead.

---

## 3. Enterprise Master MCP Reference Architecture

### Layer A: Inbound Edge and Auth
Responsibilities:
- External URL correctness and OAuth discovery
- Host/origin enforcement
- Tenant identity resolution

FastMCP alignment:
- AuthProvider with correct base_url and mcp_path handling
- host_origin_protection enabled with explicit allowlists

### Layer B: Capability Registry and Contract Normalization
Responsibilities:
- Canonical capability IDs
- Alias/shape coercion
- Schema and example publication

FastMCP alignment:
- Pydantic-driven schemas
- Extended discovery output
- x-mcp-header annotations for routing-critical params

### Layer C: Downstream Provider Adapters
Responsibilities:
- Provider-specific auth attachments
- Parameter adaptation
- Error mapping and retries

FastMCP alignment:
- Proxy and client transport consistency
- Modern header-based routing compatibility

### Layer D: Resilience and Orchestration
Responsibilities:
- Circuit breaker per remote
- Timeout isolation
- Degraded-mode fallbacks

FastMCP alignment:
- Stateless multi-worker deployment
- EventStore for long operations

### Layer E: Observability and Governance
Responsibilities:
- Structured logs and audit
- Capability-level success/error SLOs
- Tenant-scoped operational diagnostics

FastMCP alignment:
- Middleware instrumentation
- Optional OTel support path

---

## 4. Tenant-Control Model for Downstream Dependencies
Master MCP should enforce tenant controls in this order:
1. Capability allowlist per tenant
2. Scope and auth profile checks per capability
3. Provider routing policy (preferred, fallback, blocked)
4. Egress restrictions by provider domain
5. Runtime kill-switch per downstream provider/tool

Recommended metadata fields per capability:
- capability_id
- provider
- required_scopes
- tenant_policy_tag
- reliability_tier
- fallback_mode
- pii_classification

---

## 5. Non-Disruptive Adoption Path (1.0.3)

Phase 1 (additive, low risk)
- Keep existing tool names and flows.
- Add capability registry and schema-rich discovery.
- Add structured error envelope categories.

Phase 2 (compatibility wrappers)
- Add alias and shape normalization.
- Add x-mcp-header annotations for tenant and routing keys.
- Preserve old payload forms.

Phase 3 (governed orchestration)
- Introduce per-tenant capability policies.
- Introduce provider scorecards and automated drift checks.
- Add workflow wrappers for high-value tasks.

This path avoids disruptive client breakage.

---

## 6. Specific Recommendations for anticafarmacia_mcp

### 6.1 Immediate
1. Keep stateless HTTP enabled for production scaling.
2. Add host_origin_protection and explicit allowed host/origin lists.
3. Validate base_url and downstream URLs in startup diagnostics.
4. Add capability schema introspection endpoint/tool with examples.

### 6.2 Near-term
1. Add x-mcp-header annotations for tenant routing parameters.
2. Add normalized error categories for downstream failures.
3. Add long-operation strategy with EventStore for export/import flows.

### 6.3 Governance
1. Add tenant capability policies in master layer.
2. Add downstream provider contract tests (schema and error compatibility).
3. Add operational scorecard tool for tenant admins.

---

## 7. Risks to Avoid
1. Tight coupling to raw downstream tool names.
2. Auth route misconfiguration when mounting under prefixes.
3. Assuming custom routes are authenticated.
4. Relying on sticky sessions in horizontally scaled setups.
5. Exposing wildcard CORS in production.

---

## 8. Success Criteria
- First-attempt call success increases significantly for AI clients.
- Validation failures from naming/shape mismatch drop sharply.
- Downstream outages degrade gracefully without master MCP failure.
- Tenant-level policy controls become explicit and auditable.

---

## 9. Bottom Line
FastMCP 4.0.x is well-suited for an enterprise master MCP pattern. The right architecture is contract-first and policy-centric:
- FastMCP handles protocol and transport machinery.
- The master MCP owns normalized capabilities, governance, and resilience.
- Downstream MCPs remain pluggable dependencies under tenant-controlled policy.
