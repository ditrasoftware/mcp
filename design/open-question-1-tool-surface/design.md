# Question 1: Unified Tool Names vs Strict Namespaces

## Question

Should the federator expose one flat tool catalog or preserve strict namespaces per downstream MCP?

## Expert Recommendation

Use strict namespaces as the default contract, and add an optional curated global alias layer.

## Why This Is Best

1. Operational safety
- Prevents accidental collisions when two remotes export similarly named tools.
- Reduces blast radius when one downstream changes a tool contract.

2. Governance and auditability
- Every invocation can be traced to a specific remote and trust boundary.
- Security reviews and incident analysis remain straightforward.

3. Evolution without breaking clients
- Canonical namespaced IDs stay stable.
- Aliases can be added, updated, or removed through policy without touching downstream services.

## Suggested Naming Model

1. Canonical name
- namespace.remote.tool

2. Optional alias
- human-friendly short name mapped by policy to canonical target.
- only for approved, non-ambiguous tools.

## Conflict Resolution Policy

1. If two remotes claim the same alias candidate, do not auto-resolve.
2. Mark alias as conflicted and require explicit operator mapping.
3. Keep canonical names callable at all times.

## Client Experience Pattern

- Discovery endpoints return canonical names and available aliases.
- Route-resolution endpoint explains selected backend and reason.
- UI can display friendly names while invoking canonical IDs.

## Implementation Notes

- Keep current namespaced mount behavior as baseline.
- Add an alias registry object in gateway settings.
- Expose alias-to-canonical mappings via a diagnostic tool endpoint.
