# Ditra DevTest MCP

Ditra DevTest MCP is a FastMCP federator test harness designed to validate:

- Main MCP routing and policy behavior
- Downstream MCP integration with `anticafarmacia_mcp`
- Toolbox remotes (`/mcp/mssql`, `/mcp/mysql`) as working examples from FerreroMed patterns
- Direct and mounted remote-call use cases
- Runtime configuration and override scenarios

## Structure

```
ditra_devtest_mcp/
├── __init__.py
├── __main__.py
├── auth.py
├── oauth.py
├── rest_client.py
├── settings.py
├── server.py
├── artifacts/
│   ├── tools/
│   ├── resources/
│   ├── prompts/
│   └── apps/
├── gateway/
├── providers/               # Compatibility wrappers + adapters
├── Dockerfile
├── build.sh
├── fastmcp.json
├── .env_example
├── docker-compose-mcp.yml
└── docker-compose-devtest-stack.yml
```

## What This MCP Tests

1. Federator route resolution
- `gateway_resolve_tool_route`
- `gateway_get_route_policy`

2. Remote connectivity and discovery
- `gateway_list_backends`
- `gateway_health_check`
- `gateway_list_remote_tools`

3. Remote invocation
- `gateway_call_remote_tool`
- passthrough vs normalized direct result strategy

4. FastMCP-first architecture elements
- mounted remotes via proxy
- direct remotes via FastMCP client
- middleware compatibility shaping
- custom route health checks

## Downstream Defaults

Without `DITRA_DEVTEST_GATEWAY_REMOTES_JSON`, this server auto-wires:

1. AnticaFarmacia downstream MCP
- name: `anticafarmacia-mcp`
- namespace: `anticafarmacia_mcp`
- url: `http://anticafarmacia-mcp:8002/mcp`

2. Toolbox MSSQL remote
- name: `toolbox-mssql`
- namespace: `toolbox_mssql`
- url: `http://toolbox:5000/mcp/mssql`

3. Toolbox MySQL remote
- name: `toolbox-mysql`
- namespace: `toolbox_mysql`
- url: `http://toolbox:5000/mcp/mysql`

## Quick Start

### 1) Local Federator Only

```bash
cd servers/ditra_devtest_mcp
cp .env_example .env
docker compose -f docker-compose-mcp.yml up -d
```

### 2) End-to-End Devtest Stack

Starts this MCP plus `anticafarmacia_mcp` as a downstream remote.

```bash
cd servers/ditra_devtest_mcp
docker compose -f docker-compose-devtest-stack.yml up -d --build
```

To include toolbox container in the same stack, provide image and enable profile:

```bash
export TOOLBOX_MCP_IMAGE=your-registry/toolbox-mcp:latest
docker compose -f docker-compose-devtest-stack.yml --profile toolbox up -d
```

## Runtime Configuration Patterns

### Pattern A: Auto Defaults

Use env toggles and default remote wiring:

```bash
export DITRA_DEVTEST_GATEWAY_ENABLE_ANTICAFARMACIA=true
export DITRA_DEVTEST_GATEWAY_ANTICAFARMACIA_URL=http://anticafarmacia-mcp:8002/mcp
export DITRA_DEVTEST_GATEWAY_ENABLE_TOOLBOX=true
```

### Pattern B: Fully Dynamic Remote JSON

Override all remotes at runtime:

```bash
export DITRA_DEVTEST_GATEWAY_REMOTES_JSON='[
  {"name":"anticafarmacia-mcp","namespace":"anticafarmacia_mcp","type":"streamable-http","url":"http://anticafarmacia-mcp:8002/mcp"},
  {"name":"toolbox-mssql","namespace":"toolbox_mssql","type":"streamable-http","url":"http://toolbox:5000/mcp/mssql"},
  {"name":"toolbox-mysql","namespace":"toolbox_mysql","type":"streamable-http","url":"http://toolbox:5000/mcp/mysql"}
]'
```

### Pattern C: Per-Tool Route Overrides

```bash
export DITRA_DEVTEST_GATEWAY_TOOL_ROUTE_OVERRIDES_JSON='{
  "inventory_list": "remote",
  "health_check": "local"
}'
```

## Core Gateway Tools

- `gateway_list_backends()`
- `gateway_health_check(remote_name=None)`
- `gateway_list_remote_tools(remote_name)`
- `gateway_resolve_tool_route(tool_name, force_remote=False)`
- `gateway_get_route_policy()`
- `gateway_call_remote_tool(remote_name, tool_name, arguments=None, force_remote=False, result_strategy=None)`
- `registry_summary()`

## Notes on Toolbox Examples

Toolbox integration in this MCP follows the same endpoint pattern used by FerreroMed:

- `http://toolbox:5000/mcp/mssql`
- `http://toolbox:5000/mcp/mysql`

This makes the devtest environment representative of current production gateway integration patterns.

## FastMCP Runtime

- transport: streamable HTTP (default)
- stateless HTTP: enabled by default
- custom liveness route: `/health`
- custom readiness route: `/ready`
- proxy mount + direct client calls both supported

## Build

The build script mirrors the deployment-style flow used by AnticaFarmacia, but its key values can be overridden for CI or release automation:

```bash
PROJECT_ID=your-project IMAGE_NAME=ditra-devtest-mcp TAG=1.0.1 PUSH_IMAGE=false ./build.sh
```

## Troubleshooting

1. Remote appears configured but not reachable
- check `gateway_health_check()` output
- verify Docker network and service DNS names

2. Tool route is unexpected
- run `gateway_resolve_tool_route()`
- verify `DITRA_DEVTEST_GATEWAY_MODE`, `ROUTE_POLICY`, and route overrides

3. Auth failures on downstream MCPs
- set remote-specific auth in `DITRA_DEVTEST_GATEWAY_REMOTE_*` vars
- or use `DITRA_DEVTEST_GATEWAY_REMOTES_JSON` with `auth` value

