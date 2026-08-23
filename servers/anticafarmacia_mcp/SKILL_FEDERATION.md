# Skill Federation Architecture

## Overview

**Skill Federation** is a pattern for decentralized, discoverable AI capabilities across MCP networks. Instead of a centralized capability registry, each MCP owns its domain-specific skills and exposes them for upstream discovery and composition.

**Pattern Flow**:
```
google_workspace_mcp (skills owner)
        ↓ exposes capabilities
anticafarmacia_mcp (gateway)
        ↓ discovers + normalizes
upstream client (Claude, etc.)
        ↓ invokes federated skills
downstream skill execution (google_workspace MCP)
```

## Terminology

| Term | Definition |
|------|-----------|
| **Skill** | A discoverable, composable AI capability (tool, resource, prompt) with metadata |
| **Capability** | Technical spec of a skill (input/output schema, auth, errors) |
| **Federation** | Pattern where MCPs expose capabilities for upstream discovery |
| **Normalization** | Transform remote capabilities to canonical (anticafarmacia) format |
| **Skill Owner** | The MCP that implements and exposes a skill (e.g., google_workspace_mcp) |
| **Skill Gateway** | The MCP that discovers and routes to skill owners (anticafarmacia_mcp) |

## Architecture Components

### 1. Skill Owner: google_workspace_mcp

**What it exposes**:
- Capability Registry endpoint: `/capability/registry`
- Tool capabilities: Gmail, Drive, Sheets, Docs operations
- Resource endpoints: OpenAPI schemas, service manifests
- Metadata: Auth requirements, error categories, PII classification

**Example capability contract** (from google_workspace_mcp):
```json
{
  "capability_id": "gmail.send_message",
  "tool_name": "gmail_send_message",
  "version": "1.0",
  "description": "Send an email via Gmail API",
  "input_schema": {
    "type": "object",
    "properties": {
      "to": {"type": "string"},
      "subject": {"type": "string"},
      "body": {"type": "string"}
    },
    "required": ["to", "subject", "body"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "message_id": {"type": "string"},
      "timestamp": {"type": "string"}
    }
  },
  "auth_profile": "service",
  "required_scopes": ["gmail.send"],
  "reliability_tier": "tier_a",
  "error_categories": ["AUTH_ERROR", "VALIDATION_ERROR", "RATE_LIMIT_ERROR"],
  "pii_classification": "high"
}
```

### 2. Skill Gateway: anticafarmacia_mcp

**Discovery Process**:

```python
# 1. Query google_workspace_mcp's capability registry
GET https://workspace.dchat.ditra.app/mcp/capability/registry
Authorization: Bearer <token>

# Response: { "gmail_send_message": {...}, "drive_upload_file": {...}, ... }

# 2. For each capability, fetch detailed schema
GET https://workspace.dchat.ditra.app/mcp/tools/gmail_send_message

# 3. Normalize to anticafarmacia format
- ID: federated.google_workspace.gmail_send_message
- Scopes: anticafarmacia:federated:google_workspace:gmail.send
- Auth: Map google_workspace auth → anticafarmacia OAuth 2.1
- Errors: Merge with anticafarmacia error standards

# 4. Register as local tool wrapper
@mcp.tool(name="federated_google_workspace_gmail_send_message")
async def wrapper(**kwargs):
    # Route through gateway to google_workspace_mcp
    # Apply auth transformation
    # Normalize response
    # Adapt errors
    return result
```

**Normalization Rules**:

| Aspect | Transformation |
|--------|---|
| **ID** | `capability_id` → `federated.<namespace>.<tool_name>` |
| **Tool name** | `tool_name` → `federated_<namespace>_<tool_name>` |
| **Scopes** | `[scope]` → `anticafarmacia:federated:<namespace>:<scope>` |
| **Auth profile** | Inherit, map to OAuth 2.1 if needed |
| **Error categories** | Merge with anticafarmacia standards |
| **Reliability tier** | Inherit or downgrade if remote is unstable |
| **PII classification** | Inherit or escalate based on flow |

### 3. Skill Discovery Flow

```python
# File: artifacts/skill_federation.py
class RemoteMCPIntrospector:
    async def discover_capabilities(self) -> dict:
        """
        Multi-strategy discovery:
        1. Try /capability/registry (FastMCP 4.0.x standard)
        2. Try /capabilities (alternate naming)
        3. Try /.well-known/mcp/capabilities (well-known endpoint)
        4. Try /_mcp/introspection (MCP introspection protocol)
        """

class SkillNormalizer:
    def normalize_capability(self, remote_capability):
        """Transform remote format → anticafarmacia format"""
        
    def adapt_auth_requirements(self, contract, auth_config):
        """Bridge remote auth → upstream auth model"""
        
    def adapt_error_normalization(self, contract, error_mapping):
        """Map remote errors → anticafarmacia errors"""

class FederatedSkillRegistry:
    """Maintains discovered skills, handles caching and invalidation"""

async def load_federated_skills(registry, settings):
    """
    Main discovery orchestrator:
    1. Iterate over all enabled remote MCPs
    2. Introspect each MCP's capabilities
    3. Normalize each capability
    4. Adapt auth and error handling
    5. Register in federated registry
    """
```

### 4. Skill Routing & Execution

```python
# File: artifacts/skill_federation_integration.py

async def initialize_federated_skills(mcp, client, settings):
    """
    Server startup integration:
    1. Create FederatedSkillRegistry
    2. Call load_federated_skills()
    3. Create tool proxies for each skill
    4. Register skill discovery resource
    """

def create_federated_skill_tools(mcp, registry, client, settings):
    """
    For each registered skill:
    1. Create async tool function
    2. Register with @mcp.tool()
    3. Implement routing logic:
       - Extract auth from upstream request
       - Build gateway routing request
       - Call remote MCP tool via gateway
       - Normalize response
       - Adapt errors
       - Return result to upstream client
    """
```

## Integration Points

### 1. Server Startup

```python
# In server.py
from artifacts.skill_federation_integration import initialize_federated_skills

async def create_mcp():
    mcp = FastMCP(...)
    
    # Load local artifacts
    local_tools, local_resources = artifacts.load_local(...)
    
    # Load federated skills from downstream MCPs
    federated_registry = await initialize_federated_skills(mcp, client, settings)
    
    return mcp, federated_registry
```

### 2. Observability Resource

```python
# Clients can query: anticafarmacia://skills/federated/registry
GET /resource/anticafarmacia://skills/federated/registry

# Returns:
{
  "schema_version": "1.0",
  "total_skills": 45,
  "by_remote_mcp": {
    "google_workspace_mcp": 25,
    "google_toolbox_mcp": 20
  },
  "skills": [
    {
      "skill_id": "federated.google_workspace.gmail_send_message",
      "remote_mcp": "google_workspace_mcp",
      "remote_tool_name": "gmail_send_message",
      "title": "Send Gmail Message",
      "description": "Send an email via Gmail API",
      "category": "communication",
      "requires_auth": true,
      "reliability_tier": "tier_a",
      "pii_classification": "high"
    },
    ...
  ]
}
```

### 3. Skill Discovery Tool

```python
# Clients can query available skills
POST /tools/list_federated_skills
{
  "filter_by_remote_mcp": "google_workspace_mcp",
  "filter_by_category": "communication"
}

# Returns:
{
  "total_available": 8,
  "skills": [
    {
      "skill_id": "federated.google_workspace.gmail_send_message",
      "title": "Send Gmail Message",
      "local_tool_name": "federated_google_workspace_gmail_send_message",
      ...
    },
    ...
  ]
}
```

## Applying Pattern to Other MCPs

### Step 1: Create Custom Normalizer

For each skill type (communication, document, analytics, etc.), create domain-specific normalizers:

```python
# artifacts/skill_normalizers/workspace_normalizer.py

class GoogleWorkspaceNormalizer(SkillNormalizer):
    """Normalize Google Workspace skills (Gmail, Drive, Sheets, Docs)"""
    
    def adapt_auth_requirements(self, contract, auth_config):
        # Map Google OAuth scopes → anticafarmacia scopes
        google_scopes = auth_config.get("scopes", [])
        adapted_scopes = [
            f"anticafarmacia:federated:google_workspace:{scope.split('.')[-1]}"
            for scope in google_scopes
        ]
        contract.required_scopes = tuple(adapted_scopes)
        
        # Document Google-specific auth details
        contract.routing_hints["google_auth_type"] = "oauth2"
        contract.routing_hints["google_scopes"] = google_scopes
        
        return contract
```

### Step 2: Register Normalizer

```python
# In skill_federation.py or config
NORMALIZER_REGISTRY = {
    "google_workspace_mcp": GoogleWorkspaceNormalizer,
    "google_toolbox_mcp": GoogleToolboxNormalizer,
    "my_custom_mcp": CustomNormalizer,
}
```

### Step 3: Update Server Config

```bash
# In docker-compose.yml or .env
export ANTICAFARMACIA_GATEWAY_REMOTES_JSON='[
  {
    "name": "google-workspace-mcp",
    "namespace": "google_workspace",
    "type": "streamable-http",
    "url": "https://workspace.dchat.ditra.app/mcp",
    "auth": "Bearer YOUR_TOKEN",
    "enabled": true
  },
  {
    "name": "custom-mcp",
    "namespace": "custom",
    "type": "streamable-http",
    "url": "https://custom.example.com/mcp",
    "auth": "Bearer CUSTOM_TOKEN",
    "enabled": true
  }
]'
```

## Data Flow Example: "Send Gmail via anticafarmacia_mcp"

```
1. Claude sends skill call to anticafarmacia_mcp:
   POST /tools/federated_google_workspace_gmail_send_message
   {
     "to": "user@example.com",
     "subject": "Hello",
     "body": "How are you?"
   }
   Headers: Authorization: Bearer <claude_token>

2. anticafarmacia_mcp receives request:
   - Tool matched: federated_google_workspace_gmail_send_message
   - Skill found in registry: federated.google_workspace.gmail_send_message
   - Local tool wrapper called with arguments

3. Wrapper extracts auth & constructs gateway request:
   Gateway routing request:
   {
     "remote_mcp": "google_workspace_mcp",
     "tool_name": "gmail_send_message",
     "arguments": {to, subject, body},
     "routing_hints": {
       "domain": "google_workspace",
       "operation": "gmail_send_message",
       "remote_auth_type": "oauth2",
       "google_scopes": ["https://www.googleapis.com/auth/gmail.send"]
     }
   }

4. Gateway calls remote MCP:
   POST https://workspace.dchat.ditra.app/mcp/tools/gmail_send_message
   {arguments, routing_hints}
   Headers: Authorization: Bearer <google_workspace_token>

5. google_workspace_mcp executes:
   - Validates auth against gmail.send scope
   - Calls Gmail API
   - Returns: {"message_id": "abc123", "timestamp": "2026-08-19T..."}

6. Gateway adapts response:
   - Normalize field names if needed
   - Apply error mapping
   - Add metadata (source MCP, latency, etc.)

7. anticafarmacia_mcp returns to Claude:
   {
     "message_id": "abc123",
     "timestamp": "2026-08-19T...",
     "_metadata": {
       "skill_id": "federated.google_workspace.gmail_send_message",
       "remote_mcp": "google_workspace_mcp",
       "routing_latency_ms": 245
     }
   }

8. Claude receives skill result and continues conversation
```

## Caching & Invalidation

```python
# FederatedSkillRegistry handles caching
registry = FederatedSkillRegistry(cache_ttl_seconds=3600)

# On server startup:
await load_federated_skills(registry, settings)
registry.mark_discovery_complete("google_workspace_mcp")

# After 1 hour (or when /reload_skills called):
if not registry.is_cache_valid("google_workspace_mcp"):
    # Re-discover from this MCP
    await load_federated_skills(registry, settings)
```

## Error Handling

Skills may fail due to:
- **Network error**: Remote MCP unreachable
- **Auth error**: Token expired or insufficient scopes
- **Validation error**: Input schema violation
- **Provider error**: Remote API call failed
- **Rate limit**: Remote MCP rate limit hit

All errors are normalized to anticafarmacia categories for consistent upstream handling.

## Security Considerations

1. **Auth isolation**: Remote MCP auth tokens never exposed upstream
2. **Scope escalation**: Can't grant higher scopes than anticafarmacia provides
3. **PII handling**: Inherit PII classification from remote; escalate if needed
4. **Error masking**: Don't leak remote error details to upstream
5. **Rate limiting**: Apply anticafarmacia rate limits; aggregate with remote limits

## Performance Tuning

- **Discovery caching**: Cache TTL defaults to 3600s; tune per environment
- **Parallel discovery**: Introspect multiple MCPs concurrently
- **Schema validation**: Lazy-load detailed schemas; cache after first access
- **Tool proxy creation**: Defer until skill first accessed (lazy initialization)

## Next Steps

1. **Implement Gateway Routing**: Update `gateway/direct.py` to route federated skill calls
2. **Add Auth Transformation**: Implement OAuth 2.1 → downstream auth mapping in middleware
3. **Build Skill Composition**: Combine multiple federated skills in compound operations
4. **Add Metrics**: Track skill usage, latency, errors via Prometheus/CloudWatch
5. **Skill Marketplace**: Create registry of available skills across all deployed MCPs
