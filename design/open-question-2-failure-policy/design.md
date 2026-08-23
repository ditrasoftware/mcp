# Question 2: Fail-Closed vs Fail-Open Defaults

## Question

Should remote failures fail-closed or fail-open to local fallback by default?

## Expert Recommendation

Adopt a risk-tiered policy:

- fail-open for read-only and discovery operations
- fail-closed for state-changing or compliance-sensitive operations

## Why This Is Best

1. Reliability without unsafe side effects
- Users still receive value during partial outages for non-destructive paths.
- Mutating actions never run under ambiguous execution guarantees.

2. Better user trust
- Predictable behavior for write operations.
- Clear degraded-mode semantics for read paths.

3. Regulatory and business alignment
- Avoid duplicate writes, partial writes, or inconsistent transactional effects.
- Keep sensitive actions explicit and auditable.

## Policy Matrix

1. Read-only tools
- default: fail-open if local equivalent exists
- if no fallback exists: return typed degraded response

2. Mutating tools
- default: fail-closed
- require explicit override to allow fallback

3. Auth errors
- refresh once when strategy supports refresh
- then fail-closed with typed auth failure

4. Timeout spikes
- apply bounded retries
- open circuit per remote when threshold exceeded

## Response Contract

Return structured metadata in both success and failure paths:

- selected route
- fallback used flag
- policy reason
- degradation level
- correlation id

## Implementation Notes

- Add per-tool risk class metadata in the capability catalog.
- Enforce policy before connector invocation.
- Emit standardized error objects for downstream and auth failures.
