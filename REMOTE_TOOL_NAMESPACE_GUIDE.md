# Remote Tool Namespace System

**Date**: 2026-08-17  
**Purpose**: Enable easy calling of downstream MCP tools with collision-free naming and minimal friction  

---

## Problem Statement

When multiple remote MCPs are mounted (e.g., `google-workspace-mcp`, `google-toolbox-mcp`), developers face two challenges:

1. **Tool Name Collisions**: Multiple remotes might expose tools with the same name (e.g., both have `list_users`).
2. **Calling Friction**: Requires knowing remote name + tool name separately; current API requires explicit parameters.

Example of collision problem:
```
google-workspace-mcp  →  list_users, create_event, add_members
google-toolbox-mcp    →  list_users, create_doc, share_file
                           ↑ collision: which list_users?
```

---

## Solution: Unified Namespace System

### 1. **Namespaced Tool Names**

All remote tools are accessible via a unique, global namespace pattern:

```
remote:<remote_name>:<tool_name>
```

**Examples**:
- `remote:google-workspace-mcp:list_users` (Google Workspace version)
- `remote:google-toolbox-mcp:list_users` (Google Toolbox version)
- `remote:google-workspace-mcp:create_event`
- `remote:google-toolbox-mcp:create_doc`
- `remote:google-toolbox-mcp:share_file`

**Benefits**:
- ✅ Globally unique (no collisions)
- ✅ Self-documenting (tool source is visible)
- ✅ Easy to parse and route
- ✅ Compatible with MCP protocol constraints

---

## API: New Gateway Tools

### 1. `gateway_discover_remote_tools()`

**Purpose**: Discover all tools on all remotes with collision detection.

**Returns**:
```json
{
  "tools_by_remote": {
    "google-workspace-mcp": [
      { "name": "list_users", "remote": "google-workspace-mcp", "full_name": "remote:google-workspace-mcp:list_users" },
      { "name": "create_event", "remote": "google-workspace-mcp", "full_name": "remote:google-workspace-mcp:create_event" }
    ],
    "google-toolbox-mcp": [
      { "name": "list_users", "remote": "google-toolbox-mcp", "full_name": "remote:google-toolbox-mcp:list_users" },
      { "name": "create_doc", "remote": "google-toolbox-mcp", "full_name": "remote:google-toolbox-mcp:create_doc" }
    ]
  },
  "namespaced_tools": {
    "remote:google-workspace-mcp:list_users": { "name": "list_users", "remote": "google-workspace-mcp", ... },
    "remote:google-workspace-mcp:create_event": { "name": "create_event", "remote": "google-workspace-mcp", ... },
    "remote:google-toolbox-mcp:list_users": { "name": "list_users", "remote": "google-toolbox-mcp", ... },
    "remote:google-toolbox-mcp:create_doc": { "name": "create_doc", "remote": "google-toolbox-mcp", ... }
  },
  "collisions": {
    "list_users": ["google-workspace-mcp", "google-toolbox-mcp"]
  },
  "collision_summary": "Tool name collisions detected (1 total):\n  • 'list_users' found in: google-toolbox-mcp, google-workspace-mcp\n\nUse full names to disambiguate:\n  • remote:google-toolbox-mcp:list_users\n  • remote:google-workspace-mcp:list_users",
  "total_remotes": 2,
  "total_tools": 4,
  "collision_count": 1
}
```

**Usage**:
```python
discovery = await call_tool("gateway_discover_remote_tools")
print(discovery["collision_summary"])  # See which tools collide
namespaced = discovery["namespaced_tools"]
# Now use keys from namespaced for unambiguous tool names
```

---

### 2. `gateway_call_tool_namespaced(full_name, arguments=None, result_strategy=None)`

**Purpose**: Call a remote tool by its full namespaced name.

**Parameters**:
- `full_name` (str): Full namespaced name, e.g., `"remote:google-workspace-mcp:list_users"`
- `arguments` (dict, optional): Tool arguments
- `result_strategy` (str, optional): `"passthrough"` (default) or `"normalized"`

**Returns**: Tool result (same as calling the tool directly)

**Examples**:

```python
# Call Google Workspace's list_users
result = await call_tool("gateway_call_tool_namespaced", {
    "full_name": "remote:google-workspace-mcp:list_users",
    "arguments": {"max_results": 10}
})

# Call Google Toolbox's create_doc
result = await call_tool("gateway_call_tool_namespaced", {
    "full_name": "remote:google-toolbox-mcp:create_doc",
    "arguments": {"title": "My Document", "folder_id": "abc123"}
})

# Call ambiguous tool unambiguously
result = await call_tool("gateway_call_tool_namespaced", {
    "full_name": "remote:google-toolbox-mcp:list_users",  # Not workspace version
    "arguments": {"filter": "active"}
})
```

**Error Handling**:
```python
try:
    result = await call_tool("gateway_call_tool_namespaced", {
        "full_name": "remote:invalid:tool_name"
    })
except Exception as e:
    print(f"Invalid namespaced tool name format: {e}")
    # Expected format: remote:<remote_name>:<tool_name>
```

---

### 3. `gateway_suggest_remote_tools(partial_name=None)`

**Purpose**: Search/suggest remote tools by partial name.

**Parameters**:
- `partial_name` (str, optional): Substring to search for. If not provided, lists all tools.

**Returns**:
```json
{
  "query": "list",
  "suggestions": [
    "remote:google-workspace-mcp:list_users",
    "remote:google-toolbox-mcp:list_users"
  ],
  "total": 2,
  "tools": {
    "remote:google-workspace-mcp:list_users": { ... },
    "remote:google-toolbox-mcp:list_users": { ... }
  }
}
```

**Usage**:

```python
# Find all tools containing "list"
suggestions = await call_tool("gateway_suggest_remote_tools", {
    "partial_name": "list"
})
for name in suggestions["suggestions"]:
    print(f"Available: {name}")

# Get all tools across all remotes
all_tools = await call_tool("gateway_suggest_remote_tools")
print(f"Total tools available: {all_tools['total']}")
```

---

### 4. `gateway_detect_tool_collisions()`

**Purpose**: Explicitly detect and report tool collisions.

**Returns**:
```json
{
  "collision_count": 1,
  "collisions": {
    "list_users": ["google-workspace-mcp", "google-toolbox-mcp"]
  },
  "collision_summary": "...",
  "resolution": "To call a colliding tool unambiguously, use gateway_call_tool_namespaced with the format: remote:<remote_name>:<tool_name>\nExample: remote:google-workspace-mcp:list_users",
  "total_remotes": 2,
  "total_tools": 4
}
```

**Usage**:

```python
collisions = await call_tool("gateway_detect_tool_collisions")
if collisions["collision_count"] > 0:
    print("⚠️ Tool collisions detected:")
    print(collisions["collision_summary"])
    print(collisions["resolution"])
```

---

## Design Principles

### 1. **Collision-Free Naming**
- Every remote tool has a globally unique name: `remote:<remote_name>:<tool_name>`
- No ambiguity; no need for hashing or prefixing

### 2. **Easy Discovery**
- `gateway_discover_remote_tools()` shows all available tools
- Collision detection is automatic and visible
- Suggestions make it easy to find tools by partial name

### 3. **Minimal Calling Friction**
- `gateway_call_tool_namespaced()` accepts the full namespaced name
- Single function call; no need to parse remote/tool separately
- Compatible with direct tool calls from MCP clients

### 4. **Per-Remote Isolation**
- Each remote is independent; failures don't cascade
- Collisions are reported but don't prevent calling
- Users choose which remote's tool to call

### 5. **Backwards Compatibility**
- Existing `gateway_call_remote_tool()` still works (requires explicit remote_name + tool_name)
- Namespace system is additive; doesn't replace existing APIs
- Mounted remotes via proxy still work (namespace:tool pattern from FastMCP)

---

## Usage Patterns

### Pattern 1: Discover → Choose → Call

```python
# Step 1: Discover all tools
discovery = await call_tool("gateway_discover_remote_tools")

# Step 2: Check for collisions
if discovery["collision_count"] > 0:
    print(f"⚠️ {discovery['collision_count']} tool collisions detected")
    print(discovery["collision_summary"])

# Step 3: Choose a specific tool
tool_name = "remote:google-workspace-mcp:list_users"

# Step 4: Call it
result = await call_tool("gateway_call_tool_namespaced", {
    "full_name": tool_name,
    "arguments": {"max_results": 20}
})
```

### Pattern 2: Search by Partial Name

```python
# Find all tools with "create" in the name
suggestions = await call_tool("gateway_suggest_remote_tools", {
    "partial_name": "create"
})

print(f"Found {suggestions['total']} tools matching 'create':")
for full_name in suggestions["suggestions"]:
    print(f"  • {full_name}")

# Call one of them
result = await call_tool("gateway_call_tool_namespaced", {
    "full_name": suggestions["suggestions"][0],
    "arguments": {...}
})
```

### Pattern 3: Explicit Collision Handling

```python
# Check for tool collisions upfront
collisions = await call_tool("gateway_detect_tool_collisions")

if "list_users" in collisions["collisions"]:
    remotes = collisions["collisions"]["list_users"]
    print(f"'list_users' collision detected: {remotes}")
    
    # Explicitly call the one you need
    if "google-workspace-mcp" in remotes:
        result = await call_tool("gateway_call_tool_namespaced", {
            "full_name": "remote:google-workspace-mcp:list_users",
            "arguments": {}
        })
    elif "google-toolbox-mcp" in remotes:
        result = await call_tool("gateway_call_tool_namespaced", {
            "full_name": "remote:google-toolbox-mcp:list_users",
            "arguments": {}
        })
```

### Pattern 4: Per-Remote Tool Exploration

```python
# Discover and organize by remote
discovery = await call_tool("gateway_discover_remote_tools")

for remote_name, tools in discovery["tools_by_remote"].items():
    print(f"\n{remote_name} ({len(tools)} tools):")
    for tool in tools:
        print(f"  • {tool['full_name']}")
```

---

## Implementation Details

### Namespace Module (`gateway/namespace.py`)

**Classes**:
- `RemoteToolInfo`: Represents a single tool on a remote
- `ToolCollision`: Represents a collision group
- `RemoteToolNamespace`: Manages namespacing and collision detection

**Key Methods**:
```python
# Create full name
full_name = RemoteToolNamespace.make_full_name("google-workspace-mcp", "list_users")
# → "remote:google-workspace-mcp:list_users"

# Parse full name
remote_name, tool_name = RemoteToolNamespace.parse_full_name(full_name)
# → ("google-workspace-mcp", "list_users")

# Check if namespaced
is_namespaced = RemoteToolNamespace.is_namespaced_tool("remote:google-workspace-mcp:list_users")
# → True

# Detect collisions
namespace = RemoteToolNamespace(gateway)
collisions = namespace.detect_collisions()
# → {"list_users": ToolCollision(...)}
```

### Gateway Functions (`gateway/direct.py`)

**New Functions**:
- `discover_remote_tools_with_namespaces(gateway)` — Async discovery with collision detection
- `call_remote_tool_by_namespace(gateway, full_name, arguments, result_strategy)` — Call by namespaced name
- `get_remote_tool_suggestions(gateway, partial_name)` — Search/suggest tools

### Server Tools (`server.py`)

**New MCP Tools**:
- `gateway_discover_remote_tools()` — MCP protocol endpoint for discovery
- `gateway_call_tool_namespaced(full_name, ...)` — MCP protocol endpoint for calling
- `gateway_suggest_remote_tools(partial_name)` — MCP protocol endpoint for suggestions
- `gateway_detect_tool_collisions()` — MCP protocol endpoint for collision reporting

---

## Error Handling

### Invalid Namespace Format

```python
try:
    result = await call_tool("gateway_call_tool_namespaced", {
        "full_name": "invalid:format"
    })
except Exception as e:
    # Error: Invalid namespaced tool name format: 'invalid:format'.
    # Expected: 'remote:<remote_name>:<tool_name>'.
    # Example: 'remote:google-workspace-mcp:list_users'
    print(f"Error: {e}")
```

### Unknown Remote

```python
try:
    result = await call_tool("gateway_call_tool_namespaced", {
        "full_name": "remote:nonexistent-remote:some_tool"
    })
except Exception as e:
    # Error: Unknown remote backend: nonexistent-remote
    print(f"Error: {e}")
```

### Remote Tool Execution Error

```python
try:
    result = await call_tool("gateway_call_tool_namespaced", {
        "full_name": "remote:google-workspace-mcp:list_users",
        "arguments": {"invalid_arg": "value"}
    })
except Exception as e:
    # Error may come from remote tool validation
    print(f"Error: {e}")
```

---

## Testing & Validation

### Unit Tests (Recommended)

```python
# Test namespace parsing
assert RemoteToolNamespace.parse_full_name("remote:google-workspace-mcp:list_users") == ("google-workspace-mcp", "list_users")
assert RemoteToolNamespace.parse_full_name("invalid") is None

# Test collision detection
namespace = RemoteToolNamespace(gateway)
namespace.add_remote_tools("remote1", [
    RemoteToolInfo("remote1", "ns1", "tool_a", "remote:remote1:tool_a"),
    RemoteToolInfo("remote1", "ns1", "tool_b", "remote:remote1:tool_b"),
])
namespace.add_remote_tools("remote2", [
    RemoteToolInfo("remote2", "ns2", "tool_b", "remote:remote2:tool_b"),  # Collision with remote1:tool_b
    RemoteToolInfo("remote2", "ns2", "tool_c", "remote:remote2:tool_c"),
])
collisions = namespace.detect_collisions()
assert "tool_b" in collisions
assert set(collisions["tool_b"].remotes) == {"remote1", "remote2"}
```

### Integration Tests (Recommended)

```python
# Test discovery with actual remotes
discovery = await discover_remote_tools_with_namespaces(gateway)
assert discovery["total_remotes"] == len(gateway.remotes)
assert len(discovery["namespaced_tools"]) > 0

# Test calling a namespaced tool
result = await call_remote_tool_by_namespace(
    gateway,
    full_name="remote:google-workspace-mcp:list_users",
    arguments={"max_results": 1}
)
assert result is not None

# Test suggestions
suggestions = await get_remote_tool_suggestions(gateway, partial_name="list")
assert any("list" in s.lower() for s in suggestions["suggestions"])
```

---

## Configuration

No new environment variables needed. The namespace system uses existing gateway configuration:
- `ANTICAFARMACIA_GATEWAY_REMOTES_JSON` — Defines available remotes
- `ANTICAFARMACIA_GATEWAY_MOUNT_ON_STARTUP` — Controls whether remotes are mounted
- Per-remote auth configuration (tokens, OAuth, etc.) — Handled by existing remote_auth.py

---

## Summary

| Feature | API | Purpose |
|---------|-----|---------|
| **Discovery** | `gateway_discover_remote_tools()` | See all remote tools with collision detection |
| **Calling** | `gateway_call_tool_namespaced(full_name, ...)` | Call a remote tool by namespaced name |
| **Suggestions** | `gateway_suggest_remote_tools(partial_name)` | Search tools by partial name |
| **Collision Detection** | `gateway_detect_tool_collisions()` | Explicitly detect naming conflicts |
| **Namespace Parsing** | `RemoteToolNamespace.parse_full_name()` | Programmatic namespace parsing |

**Key Benefits**:
- ✅ Eliminates tool name collisions
- ✅ Minimal calling friction (single function, clear naming)
- ✅ Automatic discovery and suggestions
- ✅ Transparent error handling
- ✅ Backwards compatible with existing APIs
