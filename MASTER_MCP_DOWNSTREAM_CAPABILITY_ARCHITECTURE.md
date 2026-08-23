# Master MCP Downstream Capability Architecture

## Objective
Design a robust architecture where a master MCP (example: `anticafarmacia_mcp`) can consume multiple downstream MCPs while guaranteeing:
- Reliable feature discoverability
- Cohesive and stable tool contracts
- AI-friendly invocation semantics
- Operational resilience and clear diagnostics

This document proposes an architecture standard and implementation approach for production use.

---

## 1. Core Problem
Downstream MCPs are heterogeneous:
- Different parameter naming conventions
- Different error formats
- Different auth expectations
- Different capability maturity and docs quality

Without a normalization layer, the master MCP becomes a pass-through surface with inconsistent user experience and high AI call failure rates.

---

## 2. Target Architecture (Capability Contract Model)

### 2.1 Four-layer model
1. Downstream Adapter Layer
- One adapter per downstream MCP.
- Responsible for auth attachment, health checks, raw tool discovery, and provider-specific quirks.

2. Capability Normalization Layer
- Converts raw downstream tools into standardized capability definitions.
- Applies argument aliases, shape coercion, defaults, and validation.

3. Capability Registry Layer (Master-owned contract)
- Single source of truth for all exposed capabilities.
- Stores canonical schema, examples, error taxonomy, SLA class, auth requirements.

4. Orchestration & Policy Layer
- Selects local vs remote provider.
- Applies resilience/circuit rules.
- Emits standardized responses and diagnostics.

---

## 3. Standard for "Expressed Features"
Every downstream capability should be represented in the master as a normalized descriptor:

```json
{
  "capability_id": "workspace.calendar.events.list",
  "display_name": "List Calendar Events",
  "provider": "google-workspace-mcp",
  "tool_name": "get_events",
  "version": "1.0",
  "input_schema": {},
  "aliases": {
    "calendarId": "calendar_id",
    "timeMin": "time_min",
    "timeMax": "time_max"
  },
  "example_calls": [],
  "output_schema": {},
  "error_contract": {
    "categories": [
      "VALIDATION_ERROR",
      "AUTH_ERROR",
      "API_DISABLED",
      "PROVIDER_ERROR",
      "TRANSIENT_ERROR"
    ]
  },
  "auth_profile": "oauth_user",
  "reliability_tier": "tier_b"
}
```

Key point:
- The master MCP should expose capabilities, not raw downstream tool signatures.

---

## 4. Wrapper Strategy for Cohesive Capabilities

### 4.1 Wrapper types
1. Alias Wrapper
- Accept both snake_case and camelCase.
- Map equivalent keys to canonical fields.

2. Shape Wrapper
- Support alternate payload structures.
- Normalize to canonical internal request object.

3. Workflow Wrapper
- Compose multiple downstream calls into one master capability.
- Example: export Google Doc to PDF and upload to Drive in one call.

4. Guardrail Wrapper
- Validate required fields/scopes early.
- Return actionable standard errors.

### 4.2 Canonical naming convention
Use domain-first capability IDs:
- `workspace.gmail.messages.search`
- `workspace.drive.files.search`
- `workspace.docs.export.pdf.store`

Benefits:
- Provider-independent contract
- Easy replacement of downstream implementation
- Better routing and analytics

---

## 5. Discovery & Introspection Standard
The master MCP should provide a discovery endpoint/tool that includes:
- Canonical capability ID
- Normalized input schema
- Accepted aliases
- Required auth/scopes
- Example payloads
- Error categories and hints

Minimum tools in master:
1. `gateway_discover_capabilities()`
2. `gateway_get_capability_schema(capability_id)`
3. `gateway_validate_capability_input(capability_id, payload)`
4. `gateway_capability_health()`

Outcome:
- AI clients stop guessing payloads.
- Prompt/tool planning can be deterministic.

---

## 6. Reliability and Fallback Contract

### 6.1 Capability reliability tiers
- Tier A: local implementation available
- Tier B: remote-only but stable
- Tier C: remote-only experimental or high-failure

### 6.2 Fallback behavior policy
For each capability define:
- `fallback_mode`: `none | local_alternative | cached_readonly`
- `degraded_response_template`

Example:
- If `workspace.tasks.list` fails due to API disabled, return category `API_DISABLED` with exact activation instruction.

### 6.3 Readiness split
- `/health`: process alive
- `/ready`: capability graph ready and minimum downstream quorum met

---

## 7. Auth Architecture Recommendation

### 7.1 Multi-source token strategy
Priority order per request:
1. Request-scoped token (user/session)
2. Workspace-scoped stored token
3. Service-account impersonation (if configured)
4. Static fallback token (last resort)

### 7.2 Token lifecycle controls
- Auto-refresh with persisted rotation
- Runtime token store abstraction (file/redis/secret-manager)
- Explicit auth status tool
- Explicit auth recovery tool

### 7.3 Operator diagnostics
Expose one tool that reports:
- auth mode per provider
- token freshness
- refresh success/failure counters
- missing env/secret dependencies

---

## 8. Governance & Compatibility Rules

### 8.1 Provider onboarding checklist
Before enabling a downstream MCP in production:
1. Capability mapping file completed
2. Alias and shape wrappers defined
3. Error mapping completed
4. Auth profile validated
5. Smoke tests pass

### 8.2 Versioning model
- Capability contracts versioned independently from provider version.
- Breaking provider changes are absorbed by adapter/wrapper updates.

### 8.3 Contract tests
Add CI tests for:
- Schema compatibility
- Alias acceptance
- Error normalization
- Workflow wrappers

---

## 9. AnticaFarmacia MCP as Working Example

### 9.1 What already exists (good base)
- Gateway with local/remote routing
- Namespaced remote tools
- Resilience/circuit behavior
- Remote auth refresh and health tools

### 9.2 What to add for full architecture
1. Capability registry abstraction above raw tool names
2. Standardized input alias/shape normalization per capability
3. Schema-rich discovery with examples
4. Error taxonomy enforcement in gateway responses
5. Workflow wrappers for common business tasks

### 9.3 Suggested initial capability set
Start with high-value cohesive wrappers:
- `workspace.contacts.list`
- `workspace.calendar.events.list`
- `workspace.docs.create`
- `workspace.docs.export.pdf.store`
- `workspace.drive.files.search`

Deliver these with strict contract tests and publish as reference patterns.

---

## 10. 1.0.3+ Implementation Roadmap

Phase 1: Contract Foundation
1. Introduce capability descriptor model.
2. Add discovery/schema tools.
3. Add standardized error envelope.

Phase 2: Wrapper Cohesion
1. Implement alias + shape wrappers for top 10 downstream tools.
2. Add first workflow wrappers.
3. Add provider contract tests.

Phase 3: Operational Maturity
1. Add capability-level readiness metrics.
2. Add provider scorecard dashboard output.
3. Add automated drift detection between downstream schema and master contract.

---

## 11. Success Metrics
- First-attempt tool call success rate
- Validation error rate by capability
- Auth failure rate by provider
- Mean retries per successful workflow
- % capabilities with schema + examples + tests

Target direction:
- Higher first-try success
- Lower trial-and-error prompts
- Reduced operator intervention

---

## 12. Final Recommendation
Adopt a contract-first master MCP architecture where `anticafarmacia_mcp` exposes stable, normalized capabilities rather than raw downstream tools. Keep downstream MCPs pluggable, but enforce consistency in the master via adapters, wrappers, and a capability registry.

This is the most effective approach for better AI client experience, predictable orchestration, and long-term provider interoperability.
