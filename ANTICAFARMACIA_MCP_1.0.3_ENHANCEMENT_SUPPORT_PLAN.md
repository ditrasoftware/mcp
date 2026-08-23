# AnticaFarmacia MCP 1.0.3 Enhancement Support Plan

## Purpose
This document reviews AI-client feedback from live usage of `anticafarmacia_mcp` with downstream `google-workspace-mcp`, and proposes a focused 1.0.3 enhancement plan to improve reliability, discoverability, and tool usability.

Scope of this artifact:
- Analysis and recommendations only (no runtime code changes in this task).
- Priority decisions for `anticafarmacia_mcp` as master MCP/gateway.
- Integration guidance for downstream providers (especially `google-workspace-mcp`).

---

## 1. Executive Summary
The feedback is accurate and high-signal. The largest AI-client pain point is not remote availability alone, but **poor callability of downstream tools due to schema mismatch and weak discoverability**.

For 1.0.3, prioritize three outcomes:
1. **Predictable invocation**: remove parameter guesswork with schema aliases and normalization.
2. **Operational self-healing**: stronger token lifecycle handling and clearer auth diagnostics.
3. **AI-friendly discovery**: structured tool schemas and examples surfaced through gateway tools.

If delivered, these changes should materially reduce failed attempts per task, improve first-try tool success, and make the master MCP viable under normal downstream drift.

---

## 2. Feedback Review (Validated)
The following points are consistent with observed behavior and architecture:

### 2.1 What is working
- Hybrid `local_preferred` gateway mode is appropriate.
- Namespaced remote routing model is sound for collision prevention.
- Core remote calls can succeed after re-auth and proper parameter shape.

### 2.2 What is failing for AI clients
1. **Schema mismatch / unexpected kwargs**
   - Clients use canonical Google-style names (`calendarId`, `timeMin`, `mimeType`, `body`) but wrappers may expect different names/shape.
   - Repeated trial-and-error is required.

2. **Auth fragility and inconsistent readiness**
   - Intermittent refresh token failures and API enablement gaps impact perceived reliability.
   - Error messages are not uniformly actionable at the right abstraction level.

3. **Inefficient document export flows**
   - Returning base64 blobs to clients when server-side export+store should be first-class.

4. **Insufficient discoverability for AI orchestration**
   - Tool listing exists, but argument-level schema and canonical examples are not consistently exposed in an AI-friendly way.

Conclusion: the integration is functional but not yet optimized for autonomous AI clients.

---

## 3. Root Cause Analysis

### 3.1 Contract gap between gateway and downstream wrappers
- Tool metadata does not guarantee clear parameter contracts at invocation time.
- Alias acceptance and payload coercion are inconsistent across downstream tools.

### 3.2 Missing standardized error taxonomy
- Validation errors, auth errors, and provider capability errors are not always distinguishable by machine logic.
- AI agents need deterministic error classes for automatic recovery.

### 3.3 Runtime operational gaps
- Token refresh lifecycle can degrade under missing/rotated credentials or incomplete provider setup.
- Required env vars/API enablement dependencies are not surfaced as preflight failures.

### 3.4 Workflow mismatch for binary/document operations
- AI clients should receive object references (file ids/links), not large encoded payloads by default.

---

## 4. 1.0.3 Product Objectives

### Objective A: First-try tool call success
- Reduce argument-shape failures via aliasing and normalization.

### Objective B: AI-discoverable contracts
- Expose machine-usable schemas and examples for each remote tool.

### Objective C: Hands-off auth operations
- Improve auth diagnostics and remediation pathways without requiring server restarts for common cases.

### Objective D: Server-side artifact workflows
- Add helper flows that keep large binary transforms server-side.

---

## 5. Prioritized 1.0.3 Backlog

## P0 (Must-have for 1.0.3)

### P0.1 Argument normalization compatibility shim
Add a gateway/downstream normalization layer to map common aliases and alternate payload shapes.

Minimum mappings:
- `calendarId -> calendar_id`
- `timeMin -> time_min`
- `timeMax -> time_max`
- `singleEvents -> single_events`
- `pageSize -> page_size`
- `mimeType -> mime_type`
- `body -> event` (for event management tools)
- `content_base64 -> content`

Acceptance criteria:
- Canonical Google-style kwargs and snake_case kwargs both succeed for targeted tools.
- No breaking change for existing callers.

### P0.2 Standardized error envelope
Ensure remote tool call failures return structured categories:
- `VALIDATION_ERROR`
- `AUTH_ERROR`
- `API_DISABLED`
- `PROVIDER_CONFIG_ERROR`
- `TRANSIENT_DOWNSTREAM_ERROR`

Acceptance criteria:
- Error response includes `category`, `message`, `action_hint`, and `retryable`.
- AI clients can branch recovery behavior without regex parsing.

### P0.3 Tool schema and examples in discovery
Extend gateway discovery output to include:
- `input_schema` (JSON schema)
- aliases/compatibility keys
- `example_calls` (1-2 minimal payloads)

Acceptance criteria:
- One gateway discovery call gives enough data for an AI client to construct valid calls deterministically.

---

## P1 (High-value, likely in 1.0.3 if capacity allows)

### P1.1 Server-side export-and-store helper
Add a tool such as `export_doc_to_pdf_and_save`:
- Input: `doc_id`, optional `folder_id`, optional `file_name`
- Behavior: export Google Doc as PDF and upload to Drive server-side
- Output: `file_id`, `web_view_link`, `mime_type`, `size`

Acceptance criteria:
- No base64 payload required for common document-to-drive workflows.
- Compatible with existing auth model.

### P1.2 Provider preflight diagnostics
Add/extend gateway diagnostic tool to report:
- missing env vars by provider capability
- disabled required APIs (best effort)
- auth token freshness/health summary

Acceptance criteria:
- Operators can run one diagnostic tool and get actionable deployment status.

---

## P2 (Should follow shortly after 1.0.3)

### P2.1 Capability profile per provider
Expose provider-level features and known constraints (e.g., Tasks API requirements, PSE dependency).

### P2.2 Golden-path AI examples pack
Ship compact examples for top intents:
- list contacts
- calendar events with date bounds
- doc creation/export/store
- drive search and filtering

### P2.3 Integration tests for schema compatibility
Automated tests for alias handling and error envelope consistency.

---

## 6. Recommended 1.0.3 Implementation Strategy

### Track 1: Gateway AI contract hardening
- Implement schema-rich discovery and standardized error envelope in `anticafarmacia_mcp`.
- Add normalization shim either in gateway call path or coordinated in downstream wrappers.

### Track 2: Downstream usability compatibility
- Patch high-traffic `google-workspace-mcp` tools to accept both camelCase and snake_case.
- Normalize alternate payload shapes for event and file operations.

### Track 3: Operational readiness
- Enforce preflight checks at startup/readiness and via callable diagnostics.
- Document required provider env/API dependencies explicitly.

---

## 7. AI-Client Experience Design Principles (for 1.0.3)
1. **No guessing**: every tool must advertise a machine-usable schema with examples.
2. **Loose input, strict core**: accept common aliases, normalize internally.
3. **Actionable failures**: return explicit category + remediation hint.
4. **Reference outputs over blobs**: return IDs/links whenever possible.
5. **Single-call diagnostics**: operators and AI clients should query health and capability in one place.

---

## 8. Risks and Mitigations

### Risk: Over-normalization masks user errors
Mitigation:
- Apply compatibility mappings only for known aliases.
- Emit deprecation notices in diagnostic metadata.

### Risk: Contract drift between gateway and provider
Mitigation:
- Versioned schema metadata in discovery responses.
- Integration test matrix for gateway-provider contract.

### Risk: Scope creep for 1.0.3
Mitigation:
- Keep 1.0.3 focused on P0 + one P1 feature (export-and-store) if feasible.

---

## 9. Suggested 1.0.3 Acceptance Metrics
- >= 80% reduction in `Unexpected keyword argument` failures for targeted tools.
- >= 50% reduction in retries per successful downstream workflow.
- >= 95% success on golden-path integration smoke tests.
- Auth-related failures include actionable category/hint in 100% of cases.

---

## 10. Proposed Release Notes Draft (1.0.3)
- Added AI-friendly remote tool schema discovery with examples.
- Added compatibility argument normalization for common Google-style parameters.
- Improved error classification for validation/auth/provider failures.
- Added server-side document export-and-store helper for efficient file workflows.
- Improved gateway diagnostics for provider/env/API readiness.

---

## 11. Immediate Next Steps
1. Approve P0 scope and whether to include P1.1 in 1.0.3.
2. Implement normalization + error envelope + schema discovery in a short feature branch.
3. Patch high-traffic downstream wrappers (`get_events`, `manage_event`, `create_drive_file`, export flows).
4. Add smoke tests and update docs with AI-oriented examples.

---

## 12. Recommendation
Proceed with a **contract-first 1.0.3** centered on AI-client operability, not feature breadth. The current architecture is close; the largest gains come from making downstream tools reliably callable and self-describing through the master MCP.
