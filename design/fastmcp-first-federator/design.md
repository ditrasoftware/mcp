# FastMCP-First Federator Blueprint

## Goal

Exploit FastMCP architecture fully so one main MCP can integrate multiple downstream MCPs and adjacent components with minimal custom glue code.

## FastMCP Capabilities To Maximize

1. Native mounting
- Use FastMCP proxy mounting as the default integration path for remote MCPs.
- Keep namespaced mounts as the canonical, low-friction federation mechanism.

2. Native client path
- Use FastMCP client path for policy-controlled direct invocation, health checks, and capability discovery.
- Reuse the same auth and timeout policies as mounted paths.

3. Middleware
- Use middleware for cross-cutting concerns:
  - route-policy enforcement
  - capability alias compatibility
  - diagnostics metadata injection
  - normalization shims only where required

4. Capability registration primitives
- Keep local tools, resources, prompts, and apps registered through native provider registration.
- Use these primitives to keep local and remote capability contracts consistent.

5. Custom routes
- Reserve custom routes for operational endpoints:
  - health
  - config status
  - policy state
  - catalog freshness

6. Transport flexibility
- Keep transport policy configurable at runtime.
- Maintain stateless streamable-http default for proxy-safe deployment topologies.

## Federator Composition Pattern

1. Control plane
- Configuration parsing and validation
- Runtime route policy
- Auth strategy resolution
- Remote lifecycle and health state

2. Data plane
- Mounted proxy path for transparent remote federation
- Direct client path for explicit gateway tools
- Middleware chain for policy checks and diagnostics

3. Capability plane
- Unified catalog for tools/resources/prompts/apps
- Canonical identifiers plus optional aliases
- Risk metadata and ownership tags

## Dynamic Configuration Model

1. Source hierarchy
- base config
- environment overlay
- runtime overrides

2. Activation flow
- parse and validate
- dry-run compatibility checks (connector/auth)
- atomic activation
- emit applied revision metadata

3. Safety behavior
- keep last-known-good config
- reject invalid updates without restarting
- surface typed diagnostics in operator endpoints

## Efficient Capability Taxonomy

1. Tools
- action-oriented operations
- include risk class and route hints

2. Resources
- stable data retrieval surfaces
- cache policy metadata

3. Prompts
- reusable interaction templates
- scope tags and expected tool dependencies

4. Apps
- composed task flows and UI-oriented entry points
- explicit dependency listing on tools/resources/prompts

## Practical Refactor Sequence

1. Strategy extraction
- extract connector and auth strategy interfaces from current gateway modules.

2. FastMCP path unification
- standardize mounted and direct paths to share auth, timeout, retry, and diagnostics behavior.

3. Catalog unification
- build one capability registry across local and remote kinds.

4. Dynamic config enablement
- add validation and activation lifecycle for runtime config updates.

5. Governance and quality gates
- enforce naming, schema, and documentation checks for tools/resources/prompts/apps.

## Success Criteria

- Adding a new downstream MCP requires configuration plus strategy selection, not core gateway rewrites.
- Operators can inspect route decisions, health, and config revision state from first-party endpoints.
- Clients experience a clear and predictable capability surface across tools, resources, prompts, and apps.
