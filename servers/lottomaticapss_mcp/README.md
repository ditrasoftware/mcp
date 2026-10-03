# Lottomaticapss MCP

The canonical application version is stored in `VERSION`, exported as
`lottomaticapss_mcp.__version__`, and advertised in the MCP initialize response.
Use `./set_version.sh <major.minor.patch>` before a release; `build.sh` always
tags the image from that file.

Generic scaffolding and baseline structure for Lottomaticapss MCP (Model Context Protocol) servers. This template provides:

- **Infrastructure**: Authentication, settings, REST client, gateway capabilities
- **Middleware**: Tool hash rewriting, Prefab UI rendering, iOS tap fix injection
- **Gateway Support**: Hybrid local/remote tool routing with configurable policy
- **Extensibility**: Clear TODO sections for domain-specific tools, resources, prompts, and UI apps

## Ditra Analytics (Metabase) integration

This server includes a tool/resource/prompt set that connects to the Ditra
Analytics platform — the self-hosted Metabase Pro instance behind the
`lottomatica-dashboard-webapp` procurement portal (`https://analytics.ditra.io`,
dashboard `30` "Lottomatica PSS Dashboard", collection `6` "Lottomatica PSS
Analytics"). Since this MCP is dedicated to Ditra Analytics, tool/prompt
names don't repeat a `ditra_analytics_` prefix.

- **Client**: `metabase_client.py` — MCP-first client using the canonical
  `/api/metabase-mcp` endpoint, augmented by the REST API for complete
  dashboard layouts, parameterized dashboard cards, and explicit pagination.
- **MCP-first tools**: `search`, `get_card`, `run_card_query`,
  `run_native_query`, and continuation-aware `query`.
- **Explicit REST collisions**: `api_search`, `api_get_card`,
  `api_run_card_query`, and `api_run_native_query`.
- **REST-only augmentations**: `get_dashboard`, `list_dashboard_cards`,
  `list_dashboard_cards_markdown`, `get_dashboard_card_data`, and
  `list_collection_items`. Use `list_dashboard_cards_markdown` when the caller
  requests a complete Markdown table; it renders every row server-side. Use
  `list_dashboard_cards` for complete compact card discovery. `get_dashboard`
  is compact by default; pass `full=true` for the complete (very large)
  definition. Search, dashboard-card, and collection listings accept bounded
  `limit`/`offset` pagination.
- **Saved-card visualizations**: `visualize_card` renders a card with its saved
  display and visualization settings through the `ui://lottomaticapss/saved-card.html`
  MCP App, which frames a short-lived signed static embed. It requires
  `METABASE_EMBEDDING_SECRET_KEY` and the card published for embedding (Sharing →
  Embed → Static/Guest embed → Publish). Unpublished cards return a message
  pointing to `visualize_card_query`, which uses the automatic chart viewer
  (saved pie/area/combo types are not preserved there).
- **KPI answering layer** (`analytics_assistant.py`, REST-backed):
  - `answer_dashboard_kpi` is the first choice for a saved dashboard KPI.
    Supply its name, an explicit period, and a source (e.g. `Numero Gare`,
    `2025-01-01..2026-12-31`, `PSS` or `Niuma`). It selects the saved card on
    the KPI tab, applies the dashboard's mapped date-range target, and runs
    the card in dashboard context. It reports ambiguous cards or missing
    mappings instead of guessing a model/date field. The active browser
    filter value is not available to the MCP; pass the desired period.
  - `answer_kpi` answers a question in one call, e.g. "ordinato lordo IVA di
    Novaconnect nei primi 6 mesi del 2025" → total `Ord. Lordo IVA EURO`,
    a monthly breakdown, the source, the filters applied, and the matched
    supplier field. It tries the fallbacks in this order: a saved question
    (`card_id` + `card_parameters`), then dynamic MBQL, then native SQL (only
    if permitted). If all are blocked, it returns the exact MBQL/SQL text and
    the reason. This model-based tool is for ad hoc KPIs, not reproducing
    saved dashboard tiles.
  - `discover_entity_fields` ranks the entity fields (Fornitore, Conto
    fornitore, supplier_key) with confidence and sample matches.
    `profile_field_values` returns the top values or a fuzzy match.
  - `build_mbql_query` generates typed MBQL (legacy, MBQL 5 and portable).
    `validate_mbql_query` validates a query and dry-runs it.
  - `can_run_native_query` checks native SQL permission up front, returning
    the reason and the fallback. `get_card_parameters` introspects
    saved-question parameters.
  - `list_kpi_sources` (use `evaluate=true` for live checks) and
    `describe_kpi_source` (use `expand=true` for all columns) cover source
    selection. The canonical source is model 685 `model_zrep_oda_detail`, with
    date `oda_date_for_filter` and the default filter `is_pss_order = 1`, as
    in card 840.
- **Resources**: `ditra-analytics://config`, `ditra-analytics://dashboard-summary`.
- **Prompts**: `getting_started`, `explore_dashboard_workflow`.

Configuration (see `.env_example`):

```env
METABASE_SITE_URL=https://analytics.ditra.io
METABASE_MCP_URL=https://analytics.ditra.io/api/metabase-mcp
METABASE_ACCESS_MODE=mcp_first
METABASE_API_FALLBACK_ENABLED=true
METABASE_API_KEY=
METABASE_DEFAULT_PAGE_SIZE=100
METABASE_MAX_PAGE_SIZE=500
METABASE_DEFAULT_DASHBOARD_ID=30
METABASE_DEFAULT_COLLECTION_ID=6
LOTTOMATICAPSS_KPI_SOURCE_CARD_ID=685
LOTTOMATICAPSS_KPI_DATE_FIELD=
```

Every tool result includes `_meta.backend` (`mcp` or `api`) and, where useful,
the reason REST was selected. The MCP path is the default; REST fallback can be
disabled with `METABASE_API_FALLBACK_ENABLED=false`, or all hybrid tools can be
forced to REST with `METABASE_ACCESS_MODE=api_only`.

Hashed tool names are compatibility aliases for clients that require namespaced
backend identifiers; they are not stored artifacts. In `auto` mode they are
advertised only to Claude-like clients. Set `DITRASOFTWARE_HASHED_TOOL_ALIASES`
to `always` or `never` to override this dynamically, and inspect the active
policy through `ditra-analytics://config`.

Tool/prompt descriptions and resource content are branded "Ditra Analytics";
the underlying Python module/class names and `METABASE_*` env vars keep the
literal "Metabase" naming since they map directly to the real external
system (same convention the webapp itself uses: UI branded "Ditra", technical
env vars named `METABASE_*`).

## Structure



```
lottomaticapss_mcp/
├── __init__.py              # Package init
├── __main__.py              # Entry point
├── auth.py                  # Auth helpers
├── oauth.py                 # OAuth/OIDC provider
├── rest_client.py           # Generic REST client
├── metabase_client.py       # Ditra Analytics (Metabase) REST client
├── settings.py              # Configuration
├── server.py                # MCP server + middleware
├── maps.py                  # Mapping/location resources (TODO)
├── gateway/                 # Gateway implementation (copy from ferreromed_mcp)
├── providers/
│   ├── __init__.py
│   ├── local_tools.py       # Ditra Analytics tools
│   ├── local_resources.py   # Ditra Analytics resources
│   ├── local_prompts.py     # Ditra Analytics prompts
│   └── local_apps.py        # Ditra Analytics prefab app catalog
├── apps/                    # Prefab UI apps (empty)
├── prompts/                 # Prompt templates (empty)
├── resources/               # Resource definitions (empty)
├── Dockerfile               # Docker image
├── build.sh                 # Build script
├── fastmcp.json             # FastMCP configuration
├── docker-compose-mcp.yml   # Docker Compose
└── README.md                # This file
```

## Getting Started

### 1. Set Up Environment Variables

Create a `.env` file (or set directly):

```bash
# Base REST API configuration
export LOTTOMATICAPSS_API_BASE_URL="https://api.example.com"
export LOTTOMATICAPSS_API_TIMEOUT_SECONDS=30
export LOTTOMATICAPSS_VERIFY_SSL=true
export LOTTOMATICAPSS_DEFAULT_API_KEY=""  # Optional fallback

# Gateway configuration
export LOTTOMATICAPSS_GATEWAY_MODE=hybrid
export LOTTOMATICAPSS_GATEWAY_ROUTE_POLICY=local_preferred
export LOTTOMATICAPSS_GATEWAY_MOUNT_ON_STARTUP=true
export LOTTOMATICAPSS_GATEWAY_ALLOW_DIRECT_CALLS=true
export LOTTOMATICAPSS_GATEWAY_DIRECT_RESULT_STRATEGY=passthrough  # or normalized

# Preferred: mount the canonical Ditra Analytics MCP
# Supply the production streamable HTTP endpoint through deployment configuration.
# When omitted, the gateway uses the existing METABASE_MCP_URL configuration.
# Do not set this to a Metabase REST endpoint.
export LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_URL="https://<analytics-mcp-host>/mcp"
export LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_ENABLED=true

# Authenticate the gateway to Ditra Analytics with either a service bearer token
# or the existing OAuth refresh-token variables. Keep these deployment secrets.
export LOTTOMATICAPSS_GATEWAY_REMOTE_DITRA_ANALYTICS_ACCESS_TOKEN="Bearer <service-token>"

# Advanced: configure one or more remote MCP backends explicitly. This takes
# precedence over LOTTOMATICAPSS_DITRA_ANALYTICS_MCP_URL.
export LOTTOMATICAPSS_GATEWAY_REMOTES_JSON='[
  {
    "name": "ditra-analytics",
    "namespace": "ditra_analytics",
    "type": "streamable-http",
    "url": "https://<analytics-mcp-host>/mcp",
    "auth": "__auto__"
  }
]'

# Optional: route specific tools to remote backends
export LOTTOMATICAPSS_GATEWAY_TOOL_ROUTE_OVERRIDES_JSON='{
  "my_remote_tool": "remote"
}'

# FastMCP settings
export FASTMCP_HOST=0.0.0.0
export FASTMCP_PORT=8001
export FASTMCP_STREAMABLE_HTTP_PATH=/mcp
```

With `LOTTOMATICAPSS_GATEWAY_MOUNT_ON_STARTUP=true`, FastMCP mounts the remote
as a namespaced provider. Use `tools/list` to obtain the exact mounted names;
the mount, rather than `gateway_call_remote_tool`, is the intended path for
MCP Apps tools such as `visualize_query` because it preserves the provider's
tool and UI metadata. `gateway_call_remote_tool` and
`gateway_call_tool_namespaced` remain useful for diagnostics and non-UI calls.
The gateway advertises the MCP Apps UI extension to the Analytics backend by
default (`LOTTOMATICAPSS_GATEWAY_ADVERTISE_MCP_APPS_UI=true`), which is required
for Metabase to advertise `visualize_query` and `render_drill_through`. Outer
MCP clients still need their own MCP Apps support to render those tools.

`LOTTOMATICAPSS_DITRA_ANALYTICS_OAUTH_SCOPES` defaults to the complete current
Analytics scope set, including SQL, content authoring, and MCP Apps. Changes to
this setting require reauthorizing the downstream connection because OAuth
refresh grants cannot gain scopes after issuance.

Use `gateway_list_backends`, `gateway_list_remote_tools`, and
`registry_summary` to verify the configured and mounted `ditra-analytics`
backend. `gateway_discover_remote_tools`, `gateway_suggest_remote_tools`, and
`gateway_detect_tool_collisions` expose direct-call addresses in the form
`remote:ditra-analytics:construct_query` and make any remote collisions
explicit. Local Lottomatica tools remain preferred under the default
`local_preferred` route policy. A `query_handle` accepted by the local `query`
tool can be produced by the mounted Ditra Analytics `construct_query` tool.

### Connect downstream OAuth on mcp-2

Set a high-entropy `LOTTOMATICAPSS_DOWNSTREAM_ADMIN_TOKEN` in the protected
deployment `.env`. Then open
`https://mcp.lottomatica-pss.ditra.app/admin/downstreams/ditra-analytics/connect`
and authenticate with HTTP Basic using any username and that token as the
password. The gateway registers its client, handles the PKCE callback, and
stores the refresh grant in its persistent FastMCP volume. Restart the
container once after the connection completes so FastMCP mounts the
authenticated remote. The local bootstrap script is not required for this
deployed flow.

### 2. Install Dependencies

```bash
pip install "fastmcp[apps]==4.0.0" "prefab-ui==0.19.1" "httpx>=0.27.0"
```

### 3. Implement Domain-Specific Code

Edit the TODO sections in:

- `providers/local_tools.py` - Add your domain-specific tools
- `providers/local_resources.py` - Add domain-specific resources (e.g., OpenAPI schemas)
- `providers/local_prompts.py` - Add reusable agent prompts
- `providers/local_apps.py` - Add Prefab UI console apps
- `maps.py` - Add mapping/location resources (optional)

### 4. Run the Server

#### Direct Python

```bash
python -m lottomaticapss_mcp
```

#### Docker

```bash
docker build -t ditrasoftware-mcp:latest .
docker run -p 8001:8001 \
  -e LOTTOMATICAPSS_API_BASE_URL="https://api.example.com" \
  ditrasoftware-mcp:latest
```

#### Docker Compose

```bash
docker compose -f docker-compose-mcp.yml up -d
```

### 5. Compose File Roles

- `docker-compose-mcp.yml`
  - Canonical compose file for this server folder.
  - MCP-focused local/dev stack using local `build: .`.
- `docker-compose.yml`
  - Not present in this folder by design.
  - Add only when you need a separate deployment-oriented stack (for example, prebuilt image + external networks).

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

If `LOTTOMATICAPSS_DEFAULT_API_KEY` is set, the server will use it as a fallback when no explicit credentials are provided.

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
export LOTTOMATICAPSS_DEFAULT_API_KEY="your-api-key"
# Clients can now call without explicit credentials
```

**Profile B (Bearer-Only - Strict Token Mode)**

```bash
# Don't set LOTTOMATICAPSS_DEFAULT_API_KEY
# Require explicit Bearer token or X-Api-Key header
```

### Docker Secrets

Store sensitive values in Docker secrets:

```bash
echo "your-api-key" | docker secret create ditrasoftware_api_key -
docker run --secret ditrasoftware_api_key \
  -e LOTTOMATICAPSS_DEFAULT_API_KEY_FILE=/run/secrets/ditrasoftware_api_key \
  ditrasoftware-mcp:latest
```

## Extending the Template

### Create a New MCP from This Template

```bash
# Copy the template
cp -r lottomaticapss_mcp my_custom_mcp
cd my_custom_mcp

# Edit the package name in __init__.py, __main__.py, Dockerfile, etc.
sed -i 's/lottomaticapss_mcp/my_custom_mcp/g' *.py *.yml Dockerfile

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
export LOTTOMATICAPSS_CACHE_TTL=300
export LOTTOMATICAPSS_CACHE_SCOPE=public

# Or set per-session if auth context matters:
export LOTTOMATICAPSS_CACHE_SCOPE=private
```

### Pagination for Large Listings

Limit items returned per page to avoid overwhelming clients:

```bash
# Return at most 50 items per tools/list, resources/list, etc.
export LOTTOMATICAPSS_LIST_PAGE_SIZE=50
```

### Error Masking for Production Security

Hide implementation details in error responses:

```bash
# Mask internal errors - return generic message to clients
export LOTTOMATICAPSS_MASK_ERROR_DETAILS=true
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

Lottomaticapss MCP Template - See LICENSE file
