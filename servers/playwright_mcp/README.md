# Playwright Artifact MCP

A small FastMCP server that captures web artifacts with Playwright and returns
short-lived Google Cloud Storage signed URLs. Artifact bytes are stored in GCS;
they are not returned as base64 in the MCP response.

The server is designed for multitenant use. Every artifact is written below an
authenticated tenant prefix, and a caller cannot select a different tenant by
passing a tool argument.

When no external IdP is wired, the trusted DitraChat gateway signs the
container, tenant, and user identity into a short-lived context token. One MCP
deployment can serve new containers and tenants without a per-container MCP
registry. The signed token is authoritative; unsigned request metadata is not.

## Tools

### `capture_artifact`

Capture an artifact from a public HTTP or HTTPS URL.

Arguments:

- `url`: target page URL.
- `artifact_type`: `screenshot`, `jpeg`, `pdf`, or `html`. Defaults to `screenshot`.
- `selector`: optional CSS selector. The capture is limited to the first matching element.
- `full_page`: capture the full page for screenshots. Defaults to `false`.
- `retention_mode`: `short` or `durable`. Defaults to `short`.
- `navigation_timeout_ms`: optional navigation timeout, up to the configured maximum.
- `wait_until`: `commit`, `domcontentloaded`, `load`, or `networkidle`. Defaults to `load`.
- `block_third_party_requests`: optionally block off-origin requests while loading. Defaults to `true`.
- `tenant_id`: optional consistency check. It must match the authenticated tenant.

The response contains:

- `signed_url`: a time-limited URL for downloading the artifact.
- `object_name`: the GCS object path.
- `content_type`, `size_bytes`, and `sha256`.
- `tenant_id`, `source_url`, and `artifact_type`.
- `signed_url_expires_in_seconds`.

`short` mode returns a temporary signed URL. `durable` mode also persists a
tenant-owned manifest and returns a stable `artifact_id`.

### `get_artifact_url`

Refresh the signed URL for a durable artifact:

```json
{"artifact_id": "art_<uuid>"}
```

The server verifies the caller's authenticated tenant against the manifest
before generating a new signed URL. The object may remain in GCS indefinitely,
but each download URL remains short-lived.

### `tenant_status`

Returns the authenticated tenant and whether GCS signed URLs are configured.

## Native Playwright capabilities

The facade can mount the original Playwright MCP as a namespaced backend. Its
native tools, resources, resource templates, and prompts remain available
under the `playwright` namespace, while the artifact tools remain at the root.
For example, a native tool is exposed as `playwright_<tool-name>` by FastMCP.

Compose starts the official Playwright MCP backend and points the facade at
`http://playwright_native:8931/mcp`. Set `PLAYWRIGHT_MCP_NATIVE_URL` to an
existing compatible Playwright MCP endpoint when managing that backend
separately. The facade does not reimplement or rename the native capability
contracts.

## Bucket path format

The bucket is selected by `PLAYWRIGHT_MCP_GCS_BUCKET`. The server does not
accept a bucket name or an arbitrary object path from a tool caller.

Every object uses this format:

```text
<artifact-prefix>/tenants/<tenant-id>/users/<user-id>/<yyyy>/<mm>/<dd>/<artifact-id>-<sha256-prefix>.<extension>
```

With the default settings, an example is:

```text
playwright/tenants/acme/users/gcip:user-123/2026/09/04/art_123-a1b2c3d4e5f607182930.png
```

The components are:

- `playwright`: `PLAYWRIGHT_MCP_ARTIFACT_PREFIX`, configurable.
- `tenants`: fixed isolation namespace.
- `acme`: authenticated tenant ID from the signed tenant token.
- `art_123`: generated collision-resistant artifact identifier.
- `a1b2c3d4e5f607182930`: first 20 hexadecimal characters of the artifact SHA-256.
- `png`: extension derived from `artifact_type`.
- `2026/09/02`: UTC date partition used for retention and operations.

For example, with bucket `ditra-mcp-artifacts` and tenant `ferreromed`, the
full GCS URI is:

```text
gs://ditra-mcp-artifacts/playwright/tenants/ferreromed/users/gcip:user-123/2026/09/04/<artifact-id>-<sha256>.png
```

The MCP response returns the object name and an HTTPS signed URL, not the
`gs://` URI as the download link. The signed URL expires after
`PLAYWRIGHT_MCP_SIGNED_URL_TTL_SECONDS` and is capped by
`PLAYWRIGHT_MCP_MAX_SIGNED_URL_TTL_SECONDS`.

## Authentication

Production uses standards-based MCP OAuth backed by GCIP email/password login.
OAuth clients discover `/authorize`, `/token`, and `/register`, complete PKCE,
and send the resulting access token on every tool request:

```text
Authorization: Bearer <access-token>
```

The verified access token supplies the application tenant, OAuth client, and
GCIP user subject used for artifact isolation. The optional HMAC context-token
flow remains available for trusted internal gateways:

```text
X-Tenant-ID: ferreromed
X-Tenant-Token: <signed-container-and-user-token>
```

The current token payload is instance- and user-bound. It is issued by a
trusted DitraChat gateway with `tenant_id`, `user_id`, `container_id`, and an
expiry, then signed with the shared HMAC secret. A token from another
DitraChat container is rejected. The `X-Tenant-ID` and `X-Tenant-Token` names
are retained for transport compatibility; the token is no longer tenant-only.

The token is an HMAC-SHA256 token created with
`PLAYWRIGHT_MCP_TENANT_TOKEN_SECRET`. The signed tenant ID is authoritative.
If `X-Tenant-ID`, the token, and the optional `tenant_id` argument disagree,
the request is rejected.

The token issuer or trusted gateway should create the token. A token should be
short-lived, for example 15 minutes, and the secret must not be committed to
git or placed in a client-visible configuration.

The current implementation provides the helper
`tenant_auth.issue_tenant_token(tenant_id, secret, ttl_seconds, user_id=..., container_id=...)`
for trusted server-side token issuance. It is not intended to be called by
untrusted MCP clients.

## GCS configuration

Copy `.env_example` to `.env` and set at least:

```dotenv
PLAYWRIGHT_MCP_GCS_BUCKET=ditra-mcp-artifacts
PLAYWRIGHT_MCP_TENANT_TOKEN_SECRET=replace-with-a-secret
PLAYWRIGHT_MCP_VERIFY_TENANT_TOKENS=true
```

The runtime Google service account needs permission to create objects in the
bucket and permission to sign URLs. On Compute Engine, configure
`PLAYWRIGHT_MCP_GCP_SERVICE_ACCOUNT` so URL generation uses IAM remote signing.

For local-only testing without GCS, leave the bucket empty and set:

```dotenv
PLAYWRIGHT_MCP_ALLOW_UNAUTHENTICATED_LOCAL=true
PLAYWRIGHT_MCP_VERIFY_TENANT_TOKENS=true
```

Local mode writes files under `/tmp/playwright-mcp-artifacts`. It does not
produce downloadable signed URLs and should not be used for public deployment.

## Security defaults

- Tenant tokens are required by default.
- Private, loopback, link-local, reserved, and multicast target addresses are blocked.
- Set `PLAYWRIGHT_MCP_ALLOW_PRIVATE_NETWORKS=true` only for a controlled internal deployment.
- Artifact size is limited by `PLAYWRIGHT_MCP_MAX_ARTIFACT_BYTES`.
- Browser navigation is limited by `PLAYWRIGHT_MCP_NAVIGATION_TIMEOUT_MS`.
- `networkidle` is not the default because analytics, ads, and long-polling can keep pages busy indefinitely.
- Signed URL lifetime defaults to 15 minutes and cannot exceed one hour by default.
- Browser contexts are created per capture and closed after the artifact is produced.
- Durable manifests use `<prefix>/tenants/<tenant-id>/users/<user-id>/manifests/<artifact-id>.json`.

## Run locally

```bash
cd servers/playwright_mcp
cp .env_example .env
python -m playwright_mcp --transport http
```

The HTTP endpoint is:

```text
http://127.0.0.1:8001/mcp
```

## Docker

```bash
cd servers/playwright_mcp
docker compose --env-file .env up -d
```

The default host port is `8096`.
