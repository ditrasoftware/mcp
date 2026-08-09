# FerreroMed MCP (FastMCP)

This folder contains a FastMCP 4.x server that wraps the existing FerreroMed REST API.

## Environment

- `FERREROMED_API_BASE_URL` (required)
  - Example: `https://ferreromed.ditra.io`

## Run

From repo root:

- `python -m ferreromed_mcp` (default HTTP transport)
- Or: `python -m ferreromed_mcp --transport stdio`

If you see `MCP error 404` / `Session not found` errors (commonly when running behind a
non-sticky reverse proxy, multiple workers/replicas, or inside chat-client embedded UIs),
enable stateless Streamable HTTP mode:

- Env: `FASTMCP_STATELESS_HTTP=true`
- Or CLI: `python -m ferreromed_mcp --stateless-http`

## Deployment (recommended)

### Compose File Roles

- `docker-compose-mcp.yml`
  - Canonical deployment-oriented compose in this folder.
  - Integrated REST + MCP stack intended for production-like operation.
- `docker-compose-mcp-example.yml`
  - Copy/reference example for customization.
  - Use when you want to start from a clean template before tuning environment-specific values.

### Compose Commands

- `docker compose -f docker-compose-mcp.yml up -d`
- `docker compose -f docker-compose-mcp-example.yml up -d`

Run REST + MCP as two services behind nginx-proxy (single domain):

- Classic REST stays on the existing FerreroMed FastAPI container.
- MCP over HTTP is served by the `ferreromed-mcp` container.
- Nginx routes `https://<domain>/mcp` to the MCP container.

See:

- ferreromed/api/docker-compose-letsencrypt.yml
- ferreromed/api/vhost.d/ferreromed.oxytrack.io
- ferreromed/api/RUNBOOK_MCP_REST.md

## Auth

Tools accept auth either via inbound request headers or explicit arguments:

- `Authorization: Bearer <token>`
- `X-Api-Key: <api-key>`

Auth endpoints (`/auth/login`, `/auth/refresh`) do not require auth.

## OAuth / OIDC (optional)

This MCP server can optionally expose standards-based OAuth/OIDC discovery and flows using FastMCP's
built-in auth providers. This is primarily useful for MCP clients that *won't* send `X-Api-Key`
headers (some remote connectors), but *will* perform OAuth and then send `Authorization: Bearer ...`.

Enable by setting `FERREROMED_MCP_AUTH_MODE`:

- `off` (default): no OAuth/OIDC routes; tools still accept `X-Api-Key` / `Authorization` headers
- `oidc_proxy`: run a DCR-capable OAuth proxy to an upstream OIDC provider
- `supabase`: verify Supabase JWTs and forward Supabase OAuth metadata

### Mode: `oidc_proxy` (recommended for robust OAuth)

Required environment:

- `FERREROMED_MCP_AUTH_MODE=oidc_proxy`
- `FERREROMED_MCP_BASE_URL=https://<public-host>`
- `FERREROMED_OIDC_CONFIG_URL=https://<idp>/.well-known/openid-configuration`
- `FERREROMED_OIDC_CLIENT_ID=...`
- `FERREROMED_OIDC_CLIENT_SECRET=...` (or `FERREROMED_OIDC_JWT_SIGNING_KEY=...` for public clients)

Optional:

- `FERREROMED_OIDC_REQUIRED_SCOPES=scope1,scope2`
- `FERREROMED_OIDC_ALLOWED_CLIENT_REDIRECT_URIS=http://localhost:*,https://*.example.com/*`
- `FERREROMED_OIDC_VERIFY_ID_TOKEN=true` (useful when access tokens are opaque)
- `FERREROMED_OIDC_TOKEN_ENDPOINT_AUTH_METHOD=client_secret_basic|client_secret_post|none`

Machine-to-machine:

- Obtain an access token from your IdP (often using the `client_credentials` grant).
- Call MCP tools with `Authorization: Bearer <token>`.

### Mode: `supabase`

Required environment:

- `FERREROMED_MCP_AUTH_MODE=supabase`
- `FERREROMED_MCP_BASE_URL=https://<public-host>`
- `SUPABASE_PROJECT_URL=https://<project>.supabase.co` (or `SUPABASE_URL`)

Optional token verification:

- For self-hosted Supabase (GoTrue) setups, JWTs are commonly **HS256** signed with your `JWT_SECRET` and `aud=authenticated`.
  In that case set:
  - `SUPABASE_JWT_ALGORITHM=HS256`
  - `SUPABASE_JWT_SECRET=<same value as your Supabase JWT_SECRET>` (or ensure `JWT_SECRET` is available)

  If your GoTrue `iss` claim doesn't match your chosen `SUPABASE_PROJECT_URL` (common when ports differ),
  set `SUPABASE_JWT_ISSUER` (comma-separated). Example:

  - `SUPABASE_JWT_ISSUER=https://supabase.oxytrack.io/auth/v1,https://supabase.oxytrack.io:8000/auth/v1`

- For asymmetric JWTs (RS256/ES256 with JWKS): set `SUPABASE_JWT_ASYMMETRIC_ALG=RS256` or `ES256` (default ES256)

Notes:

- OAuth/OIDC mode adds discovery endpoints and bearer-token parsing at the MCP layer.
  - Authorization server metadata: `/.well-known/oauth-authorization-server`
  - Protected resource metadata is **path-scoped** (RFC 9728). For MCP mounted at `/mcp`:
    - `/.well-known/oauth-protected-resource/mcp`
    - (Compatibility) `/.well-known/oauth-protected-resource`
- It does not automatically change how upstream REST auth is handled; tools may still forward tokens/keys to the REST API.

## ChatGPT "Widget domain is not set" warnings (Prefab templates)

ChatGPT's Apps manager may warn on Prefab UI templates like `ui://prefab/tool/<hash>/renderer.html`:
"Widget domain is not set for this template".

This server patches FastMCP's Prefab template synthesis to add `meta.ui.domain` by default using a per-tool hashed subdomain:

- `<tool_hash>.claudemcpcontent.com` (where `<tool_hash>` is the 12-hex hash in `ui://prefab/tool/<tool_hash>/renderer.html`)

You can control this behavior with:

- `FASTMCP_WIDGET_DOMAIN_MODE=claude|custom|off` (default: `claude`)
- `FASTMCP_APP_DOMAIN=<your-domain>` or `PREFAB_APP_DOMAIN=<your-domain>` (only when mode=`custom`)

## Why hosts show "aliased duplicates" in tool count

Prefab UI sometimes calls backend tools using deterministic hashed names of the form:

- `<12-hex>_<tool_name>`

Some clients (notably Claude connectors) enforce a strict allowlist based on `tools/list`, so the server *also advertises these hashed aliases* in `tools/list`. Hosts that display a raw tool count (like ChatGPT) may then show something like "76 including aliased duplicates".

Controls:

- `FERREROMED_HASHED_TOOL_ALIASES=always|auto|never` (default: `auto`)
  - `always`: always advertise hashed aliases (maximum compatibility)
  - `never`: never advertise hashed aliases (cleaner host UI)
  - `auto`: hide aliases when request headers look like ChatGPT/OpenAI; otherwise advertise them

## Claude connector: OAuth password vs API key

If Claude is using the OAuth (authorization_code + PKCE) flow, it will call:

- `GET /authorize ...` (PKCE)
- `POST /token` to exchange the code for a Bearer token

In that flow, Claude's **OAuth Password** is used as the OAuth **client secret** for `POST /token`.

This server enforces an optional shared secret via:

- `FERREROMED_OAUTH_SHARED_SECRET`

If `FERREROMED_OAUTH_SHARED_SECRET` is set and Claude's OAuth Password doesn't match, `POST /token` returns `401` and Claude will show an auth failure.

Recommended configurations:

- Simplest (PKCE-only): unset `FERREROMED_OAUTH_SHARED_SECRET` and leave Claude OAuth Password blank.
- Shared-secret: set `FERREROMED_OAUTH_SHARED_SECRET` and set Claude OAuth Password to the same value.

Separately, FerreroMed REST calls may require an API key. Prefer setting:

- `FERREROMED_DEFAULT_API_KEY` on the MCP server

instead of trying to reuse Claude's OAuth Password as an API key.

## Claude Desktop remote URL (API key)

Some Claude Desktop builds send the "OAuth ID / OAuth password" fields as HTTP Basic auth.
This MCP server will treat the Basic **password** as the API key when `X-Api-Key` is not present.

- Claude "Server URL": `https://<your-host>/mcp`
- Claude "OAuth ID": any non-empty value (ignored)
- Claude "OAuth Password": your FerreroMed API key
