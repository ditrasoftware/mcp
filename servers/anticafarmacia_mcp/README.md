# AnticaFarmacia MCP

Generic scaffolding and baseline structure for AnticaFarmacia MCP (Model Context Protocol) servers. This template provides:

- **Infrastructure**: Authentication, settings, REST client, gateway capabilities
- **Middleware**: Tool hash rewriting, Prefab UI rendering, iOS tap fix injection
- **Gateway Support**: Hybrid local/remote tool routing with configurable policy
- **Extensibility**: Clear TODO sections for domain-specific tools, resources, prompts, and UI apps

## Structure

```
anticafarmacia_mcp/
├── __init__.py              # Package init
├── __main__.py              # Entry point
├── auth.py                  # Auth helpers
├── auth_enterprise.py       # Enterprise auth (SAML, etc.)
├── oauth.py                 # OAuth/OIDC provider
├── oauth2_1.py              # OAuth 2.1 utilities (PKCE, DPoP, token binding)
├── tenant_context.py        # Multi-tenant context extraction & forwarding
├── rest_client.py           # Generic REST client
├── settings.py              # Configuration (includes OAuth 2.1 + GCIP)
├── server.py                # MCP server + middleware
├── maps.py                  # Mapping/location resources (TODO)
├── gateway/                 # Gateway implementation
│   ├── __init__.py
│   ├── direct.py
│   ├── proxy.py
│   └── remote_auth.py       # Remote MCP auth with DPoP support
├── artifacts/               # Canonical artifact registrations by type/source
│   ├── __init__.py
│   ├── tools/
│   │   ├── local.py
│   │   └── federated.py
│   ├── resources/
│   │   ├── local.py
│   │   └── federated.py
│   ├── prompts/
│   │   ├── local.py
│   │   └── federated.py
│   └── apps/
│       ├── local.py
│       └── federated.py
├── providers/               # Compatibility wrappers + adapters
│   ├── __init__.py
│   ├── local_tools.py
│   ├── local_resources.py
│   ├── local_prompts.py
│   └── local_apps.py
├── middleware/              # Observability, tenant, auth, error normalization
├── capability/              # Capability contracts and taxonomy
├── Dockerfile               # Docker image (FastMCP 4.0.0b2)
├── build.sh                 # Build & push script
├── fastmcp.json             # FastMCP configuration
├── docker-compose.yml       # Deployment compose (prod-oriented, prebuilt image)
├── docker-compose-mcp.yml   # Local dev compose (local build)
├── docker-compose.anticafarmacia_mcp.yml  # OAuth 2.1 + GCIP config example
├── .env_example             # Comprehensive env template (14 sections)
├── .env_anticafarmacia_mcp  # Test configuration with real OAuth 2.1 settings
└── README.md                # This file
```

## Getting Started

### 1. Set Up Environment Variables

Create a `.env` file (or set directly):

```bash
# Base REST API configuration
export ANTICAFARMACIA_API_BASE_URL="https://api.example.com"
export ANTICAFARMACIA_API_TIMEOUT_SECONDS=30
export ANTICAFARMACIA_VERIFY_SSL=true
export ANTICAFARMACIA_DEFAULT_API_KEY=""  # Optional fallback

# Gateway configuration
export ANTICAFARMACIA_GATEWAY_MODE=hybrid
export ANTICAFARMACIA_GATEWAY_ROUTE_POLICY=local_preferred
export ANTICAFARMACIA_GATEWAY_MOUNT_ON_STARTUP=true
export ANTICAFARMACIA_GATEWAY_ALLOW_DIRECT_CALLS=true
export ANTICAFARMACIA_GATEWAY_DIRECT_RESULT_STRATEGY=passthrough  # or normalized

# Optional: configure remote MCP backends
export ANTICAFARMACIA_GATEWAY_REMOTES_JSON='[
  {
    "name": "toolbox-mssql",
    "namespace": "toolbox_mssql",
    "type": "streamable-http",
    "url": "http://toolbox:5000/mcp/mssql"
  }
]'

# Optional: route specific tools to remote backends
export ANTICAFARMACIA_GATEWAY_TOOL_ROUTE_OVERRIDES_JSON='{
  "my_remote_tool": "remote"
}'

# Optional: bootstrap-free outbound auth mode
# When true, static env access/refresh tokens are ignored and credentials
# must be injected at runtime (request headers or runtime auth store).
export ANTICAFARMACIA_GATEWAY_DYNAMIC_AUTH_ONLY=true

# Optional: enforce trusted issuer/audience for runtime JWT credentials.
export ANTICAFARMACIA_GATEWAY_RUNTIME_AUTH_TRUSTED_ISSUERS="https://workspace.dchat.ditra.app/"
export ANTICAFARMACIA_GATEWAY_RUNTIME_AUTH_TRUSTED_AUDIENCES="https://workspace.dchat.ditra.app/mcp"

# FastMCP settings
export FASTMCP_HOST=0.0.0.0
export FASTMCP_PORT=8001
export FASTMCP_STREAMABLE_HTTP_PATH=/mcp
```

Runtime credential injection headers (per remote):

- `x-remote-<remote-name>-access-token`
- `x-remote-<remote-name>-refresh-token`
- `x-remote-<remote-name>-client-id`
- `x-remote-<remote-name>-client-secret`

Generic fallback headers are also supported (`x-remote-access-token`, etc.), but
per-remote headers are recommended for multi-remote orchestration.

### 2. Install Dependencies

```bash
pip install "fastmcp[apps]==4.0.0" "prefab-ui==0.19.1" "httpx>=0.27.0"
```

### 3. Implement Domain-Specific Code

Edit the TODO sections in:

- `artifacts/tools/local.py` - Add your domain-specific tools
- `artifacts/resources/local.py` - Add domain-specific resources (e.g., OpenAPI schemas)
- `artifacts/prompts/local.py` - Add reusable agent prompts
- `artifacts/apps/local.py` - Add Prefab UI console apps
- `maps.py` - Add mapping/location resources (optional)

## 1.0.4+ Architecture

- **Artifact-First**: Canonical artifact registration via `artifacts/*/local.py`
- **Single Release Version Source**: `VERSION` file drives build tag and capability contract version
- **No Legacy Compatibility**: All `FERREROMED_*` env vars removed; exclusively use `ANTICAFARMACIA_*`
- **Settings Naming**: Configuration class renamed to `AnticaFarmaciaSettings` (canonical)
- **RBAC Scope Prefix**: Now `anticafarmacia:` (was hardcoded to support multiple deployments)
- **Enterprise Middleware Stack** (order matters):
  1. Observability (request/response tracking)
  2. Tenant resolution (multi-tenant context)
  3. Auth enforcement (OIDC, API key, OAuth 2.1)
  4. Error normalization (standard error format)
  5. Tool-hash compatibility middleware (FastMCP 4.0.x)
- **Capability Registry**: Loaded at startup; see `capability/registry.py` for tool contracts
- **Skills Integration**: See [SKILLS_INTEGRATION.md](SKILLS_INTEGRATION.md) for google_workspace_mcp reference and federated skill discovery patterns

### Version Bump Workflow

For release bumps, update one place:

```bash
./set_version.sh 1.0.5
```

This updates:

1. `VERSION`
2. `.env_example` (`ANTICAFARMACIA_MCP_VERSION`)

`build.sh` reads from `VERSION`, and deployment compose files read image version via
`ANTICAFARMACIA_MCP_VERSION`.

### Migration from Earlier Versions

If upgrading from pre-1.0.4:

1. **Update all env vars**: Replace `FERREROMED_*` with `ANTICAFARMACIA_*` in your `.env` and deployment configs
2. **Update docker-compose**: Already standardized on `ANTICAFARMACIA_*` in compose templates
3. **Review settings.py**: No backward-compatibility bridge; ensure all config is under the new prefix
4. **Check auth builders**: Phase 1-4 builders now exclusively read `ANTICAFARMACIA_*` env vars

### 4. Run the Server

#### Direct Python

```bash
python -m anticafarmacia_mcp
```

#### Docker

```bash
docker build -t ditrasoftware-mcp:latest .
docker run -p 8001:8001 \
  -e ANTICAFARMACIA_API_BASE_URL="https://api.example.com" \
  ditrasoftware-mcp:latest
```

#### Docker Compose

```bash
# Deployment-oriented stack (default)
docker compose up -d

# MCP-focused local/dev stack
docker compose -f docker-compose-mcp.yml up -d
```

### 5. Compose File Roles

- `docker-compose.yml`
  - Deployment-oriented compose for prebuilt images and shared external networking.
  - Use this for VM/remote runtime and production-like rollout.
- `docker-compose-mcp.yml`
  - MCP-focused local/dev compose using local `build: .`.
  - Use this for rapid local iteration and isolated MCP testing.

## Configuration

### Gateway Modes

- **hybrid** (default): Use local tools by preference; fall back to remote if not found locally
- **local**: Use only local tools
- **remote**: Use only remote tools

### Route Policies

- **local_preferred**: Prefer local tools; route to remote if tool not found locally
- **remote_preferred**: Prefer remote tools; fall back to local if remote unavailable

### Direct Result Strategy

- **passthrough** (default): Return raw results from remote tools unmodified
- **normalized**: Normalize results to a standard format (content blocks, etc.)

## OAuth 2.1 & GCIP Multi-Tenant Support

AnticaFarmacia MCP includes comprehensive OAuth 2.1 support with Google Cloud Identity Platform (GCIP) for multi-tenant deployments.

### OAuth 2.1 Features

**PKCE (Proof Key for Code Exchange) - RFC 9126**
- Mandatory for OAuth 2.1 compliance
- Prevents authorization code interception attacks
- Automatically enabled for public clients
- S256 (SHA256) method enforced

```bash
export ANTICAFARMACIA_PKCE_ENABLED=true
export ANTICAFARMACIA_PKCE_METHOD=S256
export ANTICAFARMACIA_PKCE_VERIFIER_LENGTH=128
```

**DPoP (Demonstration of Proof-of-Possession) - RFC 9449**
- Binds tokens to client key pair
- Prevents token replay if stolen
- Recommended for production deployments
- Optional but strongly recommended

```bash
export ANTICAFARMACIA_DPOP_ENABLED=true
export ANTICAFARMACIA_DPOP_TOKEN_BINDING_BACKEND=memory  # or redis
```

**Token Rotation**
- Automatic refresh token rotation (OAuth 2.1 best practice)
- Configurable rotation policies: always, on_risk, never

```bash
export ANTICAFARMACIA_TOKEN_ROTATION_ENABLED=true
export ANTICAFARMACIA_TOKEN_ROTATION_POLICY=always
```

### GCIP Multi-Tenant Configuration

Enable multi-tenant support with Google Cloud Identity Platform:

```bash
# Enable GCIP
export ANTICAFARMACIA_GCIP_ENABLED=true
export ANTICAFARMACIA_GCIP_PROJECT_ID=your-gcp-project-id
export ANTICAFARMACIA_GCIP_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
export ANTICAFARMACIA_GCIP_CLIENT_SECRET=YOUR_CLIENT_SECRET

# OIDC Proxy Authentication
export ANTICAFARMACIA_MCP_AUTH_MODE=oidc_proxy
export ANTICAFARMACIA_OIDC_CONFIG_URL=https://accounts.google.com/.well-known/openid-configuration
export ANTICAFARMACIA_OIDC_CLIENT_ID=${ANTICAFARMACIA_GCIP_CLIENT_ID}
export ANTICAFARMACIA_OIDC_CLIENT_SECRET=${ANTICAFARMACIA_GCIP_CLIENT_SECRET}
export ANTICAFARMACIA_OIDC_AUTO_REGISTER_ON_AUTHORIZE=true

# Multi-Tenant Settings
export ANTICAFARMACIA_TENANT_ENABLED=true
export ANTICAFARMACIA_TENANT_EXTRACT_CLAIM=organizations  # Primary claim
export ANTICAFARMACIA_TENANT_FALLBACK_CLAIMS=org_id,organization_id,tenant_id
export ANTICAFARMACIA_TENANT_FORWARD_TO_DOWNSTREAM=true  # Forward to remote MCPs
```

Compatibility note:
When `ANTICAFARMACIA_OIDC_AUTO_REGISTER_ON_AUTHORIZE=true`, the server will
attempt a one-time automatic client registration if `/authorize` receives an
unknown `client_id` and an allowed `redirect_uri`. This helps clients recover
from stale local `client_id` state after server rebuilds or container resets.

### Tenant Context Forwarding

When enabled, the MCP automatically forwards tenant context to downstream MCPs via HTTP headers:

```
X-Tenant-ID: acme-corp
X-Org-ID: org_12345
X-MCP-Namespace: acme_corp
X-User-Roles: admin,user
X-User-Scopes: tools:read,resources:write
```

Downstream MCPs can use these headers to enforce tenant isolation and implement tenant-scoped authorization.

### Production Security Configuration

For production deployments, enable all OAuth 2.1 security features:

```bash
# Phase 1: PKCE + Multi-Tenant (Required)
export ANTICAFARMACIA_PKCE_ENABLED=true
export ANTICAFARMACIA_TENANT_ENABLED=true
export ANTICAFARMACIA_TENANT_ISOLATION_ENABLED=true

# Phase 2: DPoP + Token Rotation (Recommended)
export ANTICAFARMACIA_DPOP_ENABLED=true
export ANTICAFARMACIA_TOKEN_ROTATION_ENABLED=true

# Phase 3: Audit Logging + RBAC (Optional)
export ANTICAFARMACIA_AUDIT_ENABLED=true
export ANTICAFARMACIA_AUDIT_DESTINATION=cloudwatch  # or elk, splunk
export ANTICAFARMACIA_RBAC_ENABLED=true

# Use Redis for distributed token management
export ANTICAFARMACIA_REDIS_URL=redis://redis-cluster:6379
export ANTICAFARMACIA_DPOP_TOKEN_BINDING_BACKEND=redis
```

### Architecture: OAuth 2.1 + GCIP Flow

```
Client Browser
     |
     | (PKCE Challenge)
     v
GCIP Provider
     |
     | (Generate ID Token with tenant in "organizations" claim)
     v
AnticaFarmacia MCP (OIDC Proxy)
     | (Extract tenant from ID token)
     | (Generate access token with tenant scope)
     v
Downstream MCPs (via X-Tenant-ID header)
     | (Enforce tenant isolation)
     v
Domain-Specific Resources
```

For more details, see `.env_example` (Section 1-4) or `.env_anticafarmacia_mcp` for a complete test configuration.

## Authentication

### Authorization Header (Bearer Token)

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8001/mcp
```

### API Key Header

```bash
curl -H "X-Api-Key: <api_key>" http://localhost:8001/mcp
```

### HTTP Basic (Claude Desktop)

```bash
# Password is treated as the API key
curl -u username:<api_key> http://localhost:8001/mcp
```

### Default API Key (Server-Side Injection)

If `ANTICAFARMACIA_DEFAULT_API_KEY` is set, the server will use it as a fallback when no explicit credentials are provided.

## Gateway Tools

The MCP server provides utility tools for gateway diagnostics:

- `gateway_list_backends()` - List configured and mounted remote backends
- `gateway_call_remote_tool(remote_name, tool_name, arguments, force_remote, result_strategy)` - Call a remote tool directly
- `gateway_resolve_tool_route(tool_name, force_remote)` - Check routing decision for a tool
- `gateway_health_check(remote_name)` - Probe remote backend connectivity
- `gateway_list_remote_tools(remote_name)` - List tools from a remote backend
- `gateway_get_route_policy()` - Get current gateway policy

## Prefab UI Features

- **Hashed Tool Aliases**: Tools are automatically aliased with deterministic hashes for strict clients (e.g., Claude connectors that only allow listed tool names)
- **iOS Safari Tap Fix**: Automatic injection of a script to fix iOS Safari's "first tap triggers hover" behavior
- **Client Detection**: Automatic detection of ChatGPT, Claude, Gemini to adjust aliases and rendering

## Deployment

### Safe Auth Profiles

**Profile A (Default - Server-Side Key Injection)**

```bash
export ANTICAFARMACIA_DEFAULT_API_KEY="your-api-key"
# Clients can now call without explicit credentials
```

**Profile B (Bearer-Only - Strict Token Mode)**

```bash
# Don't set ANTICAFARMACIA_DEFAULT_API_KEY
# Require explicit Bearer token or X-Api-Key header
```

### Docker Secrets

Store sensitive values in Docker secrets:

```bash
echo "your-api-key" | docker secret create ditrasoftware_api_key -
docker run --secret ditrasoftware_api_key \
  -e ANTICAFARMACIA_DEFAULT_API_KEY_FILE=/run/secrets/ditrasoftware_api_key \
  ditrasoftware-mcp:latest
```

## Extending the Template

### Create a New MCP from This Template

```bash
# Copy the template
cp -r anticafarmacia_mcp my_custom_mcp
cd my_custom_mcp

# Edit the package name in __init__.py, __main__.py, Dockerfile, etc.
sed -i 's/anticafarmacia_mcp/my_custom_mcp/g' *.py *.yml Dockerfile

# Implement your domain-specific code in providers/
vim providers/local_tools.py
vim providers/local_resources.py
vim providers/local_prompts.py
vim providers/local_apps.py
```

### Integrate with Farmacia MCP

If your MCP needs to reference another MCP (e.g., farmacia_mcp), import and use its modules:

```python
# In providers/local_tools.py
from farmacia_mcp.providers.local_tools import register_farmacia_tools

# Register both your tools and farmacia's
local_names = register_farmacia_tools(...)
local_names.update(register_local_tools(...))
```

## Troubleshooting

### "Tool not found" errors

Check `gateway_resolve_tool_route()` to see if the tool is being routed correctly:
- Is it defined locally? (check `registry_summary()`)
- Is it available on the remote backend? (check `gateway_list_remote_tools()`)
- Is the route policy correct? (check `gateway_get_route_policy()`)

### 401 Unauthorized

- Ensure credentials are provided via Authorization header, X-Api-Key, or HTTP Basic
- Check `auth_debug()` to verify the MCP server is receiving auth headers

### Docker build failures

- Check that fastmcp[apps] version matches your target FastMCP version
- Ensure Python 3.13+ is available

## FastMCP Best Practices

### Version Pinning (Critical for Production)

Always pin exact versions in production. FastMCP and prefab-ui have frequent breaking changes in minor versions.

```bash
# ✅ Correct - Pin exact versions
pip install "fastmcp==3.0.0" "prefab-ui==0.19.1" "starlette==0.40.0"

# ❌ Wrong - Allows breaking changes
pip install "fastmcp>=3.0.0" "prefab-ui>=0.19.0"
```

### Response Caching (FastMCP 4.0.0+, SEP-2549)

Cache server responses to improve client performance. Useful when tools/resources lists or data doesn't change frequently:

```bash
# Cache responses for 5 minutes, publicly cacheable
export ANTICAFARMACIA_CACHE_TTL=300
export ANTICAFARMACIA_CACHE_SCOPE=public

# Or set per-session if auth context matters:
export ANTICAFARMACIA_CACHE_SCOPE=private
```

### Pagination for Large Listings

Limit items returned per page to avoid overwhelming clients:

```bash
# Return at most 50 items per tools/list, resources/list, etc.
export ANTICAFARMACIA_LIST_PAGE_SIZE=50
```

### Error Masking for Production Security

Hide implementation details in error responses:

```bash
# Mask internal errors - return generic message to clients
export ANTICAFARMACIA_MASK_ERROR_DETAILS=true
```

### Component Visibility with Tags

Use tags to control which tools are exposed in different contexts:

```python
# In providers/local_tools.py

@mcp.tool(tags={"public", "read-only"})
def list_items() -> str:
    """Public tool for listing items."""
    return "Items"

@mcp.tool(tags={"internal", "admin"})
def dangerous_operation() -> str:
    """Admin-only tool."""
    return "Done"

# Expose only public tools
mcp.enable(tags={"public"}, only=True)

# Or hide internal tools
mcp.disable(tags={"internal"})
```

### Health Check Endpoint

The server includes a `/health` endpoint for load balancers and Kubernetes:

```bash
# Returns 200 OK if configured
curl http://localhost:8001/health

# Returns 503 if API_BASE_URL not configured (useful for detecting misconfiguration)
```

### Custom Routes for HTTP Transport

You can add custom HTTP endpoints beyond the MCP protocol:

```python
@mcp.custom_route("/status", methods=["GET"])
async def status_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("Running")
```

### CLI Development Mode

Use FastMCP CLI for rapid development with auto-reload:

```bash
# With auto-reload on file changes
fastmcp run server.py --reload --transport http --port 8001

# With specific Python version and extra packages
fastmcp run server.py --python 3.11 --with requests --reload
```

## License

AnticaFarmacia MCP Template - See LICENSE file
