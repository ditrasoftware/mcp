# Enterprise MCP Archetype (Simplified, Consistent, Intuitive)

## Goal
Create one architecture and one file template that every MCP follows:
- Master MCP
- Domain MCPs
- Integration MCPs
- Utility MCPs

This keeps the enterprise MCP ecosystem consistent while still supporting federation, composition, and provider diversity.

---

## 1. Simple Mental Model
Use a strict 3-plane model for every MCP.

1. Context Plane
- Business context and policy.
- Tenant identity, governance, access, compliance tags.

2. Capability Plane
- What the MCP exposes.
- Stable capability contracts, schemas, examples, error categories.

3. Connector Plane
- How the MCP executes.
- Downstream MCP adapters, direct API adapters, retries, auth attachment.

Rule:
- Master MCP owns Context + Capability orchestration.
- Domain/dependency MCPs own local capability quality and connector reliability.

---

## 2. Unified Role Taxonomy
Every MCP must declare exactly one primary role:
- master: enterprise control-plane and federator
- domain: business-domain capabilities
- integration: external platform bridge
- utility: shared cross-domain primitives

This avoids architecture drift and ambiguous ownership.

---

## 3. Canonical Capability Contract
Expose normalized capabilities, not raw provider tools.

Required fields per capability:
- capability_id
- display_name
- role_owner
- version
- input_schema
- output_schema
- aliases
- error_categories
- auth_profile
- reliability_tier
- fallback_mode

Recommended error categories:
- VALIDATION_ERROR
- AUTH_ERROR
- AUTHZ_ERROR
- PROVIDER_ERROR
- TRANSIENT_ERROR
- POLICY_BLOCKED

---

## 4. One Template for All MCP Repos

## 4.1 Folder template

```text
<name>_mcp/
  __init__.py
  __main__.py
  server.py
  settings.py
  auth.py
  oauth.py
  rest_client.py

  capability/
    registry.py
    contracts.py
    normalization.py
    discovery.py

  adapters/
    mcp/
      <provider_a>.py
      <provider_b>.py
    direct/
      <api_a>.py

  orchestration/
    router.py
    policy.py
    resilience.py
    workflows.py

  gateway/
    direct.py
    proxy.py
    remote_auth.py

  observability/
    logging.py
    metrics.py
    audit.py

  tools/
    diagnostics.py
    discovery_tools.py
    business_tools.py

  prompts/
    templates.py

  resources/

  tests/
    contract/
    adapters/
    workflows/

  docs/
    ARCHITECTURE.md
    CAPABILITIES.md
    OPERATIONS.md

  docker-compose.yml
  docker-compose.example.yml
  Dockerfile
  build.sh
  .env_example
  README.md
```

## 4.2 Why this is simpler
- Same layout across every MCP.
- Clear separation between contracts, adapters, and orchestration.
- New engineers can navigate any MCP in minutes.

---

## 5. Master MCP Standard (Enterprise Archetype)
The master MCP should be intentionally thin and policy-first.

It should do:
- Tenant context resolution
- Capability registry aggregation and normalization
- Policy enforcement and routing decisions
- Workflow composition across downstream MCPs
- Unified diagnostics, audit, and health

It should not do:
- Deep provider-specific logic (push to adapter MCP)
- Ad-hoc per-tool exceptions in server entrypoint
- Raw pass-through contracts from downstream tools

---

## 6. Dependency MCP Standard
Each dependency MCP should look the same, just narrower in scope:
- High-quality contracts for its domain
- Reliable connector behavior for its providers
- Clear auth profile and diagnostics
- Contract tests for schema and error consistency

This makes the master MCP an orchestrator, not a tangle.

---

## 7. FastMCP 4.0.x Alignment (Keep It Practical)
Use FastMCP features as infrastructure, not as architecture.

Adopt as defaults:
- Stateless HTTP deployment for scale
- Host/origin protection for public endpoints
- Modern protocol negotiation with compatibility fallback
- Header-aware routing only for routing-critical fields
- EventStore strategy for long operations
- Root-correct OAuth mount configuration

Interpretation:
- FastMCP gives runtime primitives.
- Your archetype defines enterprise behavior and consistency.

---

## 8. Templating Rules (So Repos Stay Consistent)

1. Naming
- capability IDs are domain-first and provider-neutral.
- snake_case in internal code; aliases for external compatibility.

2. Configuration
- One .env_example format across all MCPs.
- Shared prefixes:
  - MCP_BASE_URL
  - MCP_ROLE
  - GATEWAY_REMOTES_JSON
  - GATEWAY_REMOTE_AUTH_STORE_PATH

3. Discovery
- Every MCP must expose:
  - discover capabilities
  - capability schema
  - input validation helper
  - capability health summary

4. Diagnostics
- Every MCP must expose:
  - auth status
  - auth recover
  - provider health
  - policy decision explain

5. Testing
- Contract tests mandatory before onboarding into master MCP.

---

## 9. Governance Standard
Use a lightweight onboarding gate for any MCP dependency:
1. Template compliance check
2. Capability contract lint
3. Error taxonomy compliance
4. Auth profile validation
5. Smoke workflow test in master MCP

No MCP is mounted in production until all five pass.

---

## 10. Minimal Migration Plan

Phase 1: Structure normalization
- Align folder shape and docs across MCP repos.

Phase 2: Contract normalization
- Introduce capability registry and aliases for each MCP.

Phase 3: Master policy centralization
- Move cross-tenant routing/policy into master orchestration.

Phase 4: Quality gates
- Enforce onboarding checks and contract tests in CI.

---

## 11. Decision Summary
Yes, you can simplify the architecture significantly.

The most effective approach is:
- One archetype
- One template
- One capability contract standard
- One governance gate

This creates an enterprise MCP fabric that is easy to reason about, consistent to operate, and scalable as a federated AI platform.
