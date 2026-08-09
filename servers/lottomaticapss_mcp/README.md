# Lottomaticapss MCP

Generic scaffolding and baseline structure for Lottomaticapss MCP (Model Context Protocol) servers. This template provides:

- **Infrastructure**: Authentication, settings, REST client, gateway capabilities
- **Middleware**: Tool hash rewriting, Prefab UI rendering, iOS tap fix injection
- **Gateway Support**: Hybrid local/remote tool routing with configurable policy
- **Extensibility**: Clear TODO sections for domain-specific tools, resources, prompts, and UI apps

## Structure

```
lottomaticapss_mcp/
├── __init__.py              # Package init
├── __main__.py              # Entry point
├── auth.py                  # Auth helpers
├── oauth.py                 # OAuth/OIDC provider
├── rest_client.py           # Generic REST client
├── settings.py              # Configuration
├── server.py                # MCP server + middleware
├── maps.py                  # Mapping/location resources (TODO)
├── gateway/                 # Gateway implementation (copy from ferreromed_mcp)
├── providers/
│   ├── __init__.py
│   ├── local_tools.py       # Domain-specific tools (TODO)
│   ├── local_resources.py   # Domain-specific resources (TODO)
│   ├── local_prompts.py     # Domain-specific prompts (TODO)
│   └── local_apps.py        # Domain-specific UI apps (TODO)
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

# Optional: configure remote MCP backends
export LOTTOMATICAPSS_GATEWAY_REMOTES_JSON='[
  {
    "name": "toolbox-mssql",
    "namespace": "toolbox_mssql",
    "type": "streamable-http",
    "url": "http://toolbox:5000/mcp/mssql"
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
