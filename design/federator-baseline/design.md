# Federator Baseline Architecture

## Objective

Provide one seamless MCP endpoint that aggregates local and remote capabilities while preserving control over routing, security boundaries, and reliability.

## FastMCP-First Constraint

All federator capabilities should be implemented with FastMCP-native primitives first, then extended only where platform-specific behavior is required.

## Core Components

1. Capability Catalog
- Polls and caches downstream tool metadata.
- Assigns canonical identity for each tool.
- Tracks freshness, source health, and version markers.

2. Routing Engine
- Applies mode (`local`, `remote`, `hybrid`) and per-tool overrides.
- Evaluates policy before execution.
- Emits routing decision diagnostics.

3. Connector Strategy Layer
- Strategy interface for downstream connection types.
- Initial adapters: streamable-http, proxy-mounted remote, direct client call.
- Future adapters: SSE, stdio bridge, queue-backed worker.

FastMCP mapping:
- Use FastMCP proxy mounting for namespaced remote capability exposure.
- Use FastMCP client for direct and policy-governed invocation paths.

4. Auth Strategy Layer
- Per-remote auth strategy resolution.
- Standardized error semantics for auth failures.
- Token refresh handling with bounded retries and circuit-open on repeated failures.

FastMCP mapping:
- Prefer native auth injection points in client/proxy initialization.
- Keep auth strategy output transport-agnostic so the same policy can be reused for mounted and direct calls.

5. Reliability Layer
- Per-remote timeouts and retry policies.
- Circuit breaker state per remote and optionally per tool family.
- Degraded-mode signaling for partial availability.

FastMCP mapping:
- Implement policy-aware reliability instrumentation through middleware and gateway diagnostic tools.

## Federated Tool Identity

Recommended canonical key format:

- source namespace: business or provider key
- remote name: configured backend identifier
- tool name: downstream tool identifier

Example structure:

- source: ferreromed
- remote: google_workspace
- tool: list_docs

Client-facing aliases can be derived from policy, but canonical identities must remain stable for auditability.

## Observability Minimum

- Route decision counters by reason.
- Per-remote latency percentiles and error classes.
- Auth refresh success/failure counters.
- Catalog freshness age and stale read counters.

Expose through FastMCP tools/routes:
- route-policy inspection
- backend health diagnostics
- registry summary

## Migration Guidance

1. Extract connector and auth interfaces from current gateway modules.
2. Introduce a capability catalog with periodic refresh.
3. Add policy-based aliasing while preserving current tool names.
4. Enable strict mode guards to ensure route-policy/mode consistency.
5. Roll out circuit breakers per remote.

## FastMCP Execution Model

1. Registration phase
- Register local tools, prompts, resources, and apps as first-class providers.
- Mount eligible remotes using namespaced proxies.

2. Request phase
- Apply middleware for policy and compatibility shaping.
- Resolve route using mode, overrides, and capability metadata.
- Execute through proxy path or direct client path according to decision.

3. Diagnostics phase
- Expose health and registry endpoints for operators.
- Return structured route and fallback metadata to callers.
