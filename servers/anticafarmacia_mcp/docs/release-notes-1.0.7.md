# AnticaFarmacia MCP 1.0.7

Date: 2026-08-22
Image: gcr.io/oxytrack-322814/ditra-anticafarmacia-mcp:1.0.7

## Summary
This release hardens inbound OAuth client handling to recover from stale client IDs and improves registration durability across container recreations.

## Changes
- Added resilient OIDC authorize fallback in `oauth.py`:
  - On `GET /authorize` with unknown `client_id`, the server now attempts one-time auto-registration when `redirect_uri` is allowed.
  - Controlled by `ANTICAFARMACIA_OIDC_AUTO_REGISTER_ON_AUTHORIZE` (default `true`).
- Added persistent FastMCP home volume in deployment compose files:
  - Mount: `/root/.local/share/fastmcp`
  - Volume: `anticafarmacia_fastmcp_home`
- Updated `.env_example` and docs to include auto-register toggle and version bump.

## Operational Notes
- This fix addresses "Client Not Registered" failures for clients that keep stale local `client_id` state.
- Registration still respects allowed redirect URI patterns.
- Existing downstream gateway auth behavior is unchanged.

## Validation Performed
- Service readiness remained healthy after rollout.
- Unknown `client_id` authorize flow transitioned from `400` to `302` (`/consent`) in a single request.
- Logs confirmed fallback execution (`OIDC auto-register succeeded ...`).

## Smoke Test
Run from repository root:

```bash
servers/anticafarmacia_mcp/test_gateway_automation.sh authorize-smoke
```
