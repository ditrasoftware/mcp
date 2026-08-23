# Question 3: User Token Propagation vs Delegated Credentials

## Question

For enterprise SSO, should the federator propagate user tokens downstream or use delegated server credentials?

## Expert Recommendation

Use delegated service credentials by default, with opt-in user-token propagation for explicitly approved downstream APIs requiring user-context authorization.

## Why This Is Best

1. Security posture
- Minimizes exposure of end-user tokens across multiple trust boundaries.
- Limits token scope and leakage blast radius.

2. Operational stability
- Fewer token-shape mismatches between providers.
- Simpler key rotation and secret governance.

3. Principle of least privilege
- Service credentials can be narrowly scoped per remote.
- User propagation can be constrained to only the endpoints that need it.

## Hybrid Model

1. Delegated mode (default)
- federator authenticates to remote using remote-specific service principal or refresh token.

2. Propagated mode (opt-in)
- enabled per remote and per tool.
- requires audience, issuer, and scope validation policy.
- uses token exchange when required instead of raw pass-through where possible.

## Guardrails

1. Never propagate tokens by default.
2. Require explicit config for each propagated tool.
3. Enforce claim validation and short token lifetimes.
4. Log propagation decisions with redacted token metadata only.
5. Disable propagation for high-risk remotes unless approved.

## Suggested Config Shape

- auth.strategy: delegated | propagated | exchanged
- auth.allowed_tools: explicit list
- auth.required_claims: issuer, audience, scopes
- auth.token_exchange: provider and endpoint settings

## Implementation Notes

- Refactor current remote auth into provider plugins.
- Add a standardized auth context object passed into connectors.
- Separate auth diagnostics from provider-specific naming to avoid Google-only assumptions.
