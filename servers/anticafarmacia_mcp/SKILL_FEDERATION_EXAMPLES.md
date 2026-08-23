# Skill Federation Implementation Examples

This document provides concrete, runnable examples of implementing skill federation for google_workspace_mcp and other remote MCPs.

## Example 1: Discovery & Normalization of google_workspace_mcp Skills

### Setup

```python
# File: artifacts/skill_normalizers/__init__.py

from .workspace_normalizer import GoogleWorkspaceNormalizer
from .toolbox_normalizer import GoogleToolboxNormalizer

NORMALIZER_REGISTRY = {
    "google_workspace_mcp": GoogleWorkspaceNormalizer,
    "google_toolbox_mcp": GoogleToolboxNormalizer,
}

def get_normalizer(mcp_name: str, namespace: str):
    """Factory for getting the right normalizer for a remote MCP."""
    normalizer_class = NORMALIZER_REGISTRY.get(mcp_name)
    if normalizer_class is None:
        # Default generic normalizer
        from ..skill_federation import SkillNormalizer
        return SkillNormalizer(mcp_name, namespace)
    return normalizer_class(mcp_name, namespace)
```

### Google Workspace Normalizer

```python
# File: artifacts/skill_normalizers/workspace_normalizer.py

from typing import Any
from ..skill_federation import SkillNormalizer
from ..capability.contracts import CapabilityContract

class GoogleWorkspaceNormalizer(SkillNormalizer):
    """
    Normalizer for Google Workspace MCP skills.
    
    Handles:
    - Gmail (send, read, manage labels)
    - Drive (upload, download, share)
    - Sheets (read, write, manage)
    - Docs (read, write)
    """
    
    SCOPE_MAPPING = {
        # Gmail
        "gmail.send": "anticafarmacia:federated:google_workspace:email.send",
        "gmail.compose": "anticafarmacia:federated:google_workspace:email.compose",
        "gmail.manage": "anticafarmacia:federated:google_workspace:email.manage",
        
        # Drive
        "drive.read": "anticafarmacia:federated:google_workspace:drive.read",
        "drive.write": "anticafarmacia:federated:google_workspace:drive.write",
        "drive.share": "anticafarmacia:federated:google_workspace:drive.share",
        
        # Sheets
        "sheets.read": "anticafarmacia:federated:google_workspace:sheets.read",
        "sheets.write": "anticafarmacia:federated:google_workspace:sheets.write",
        
        # Docs
        "docs.read": "anticafarmacia:federated:google_workspace:docs.read",
        "docs.write": "anticafarmacia:federated:google_workspace:docs.write",
    }
    
    CATEGORY_MAPPING = {
        "gmail": "communication",
        "drive": "storage",
        "sheets": "productivity",
        "docs": "productivity",
    }
    
    ERROR_MAPPING = {
        # Google API errors → anticafarmacia errors
        "unauthenticated": "AUTH_ERROR",
        "permission_denied": "AUTH_ERROR",
        "not_found": "NOT_FOUND_ERROR",
        "invalid_argument": "VALIDATION_ERROR",
        "resource_exhausted": "RATE_LIMIT_ERROR",
        "unavailable": "TRANSIENT_ERROR",
        "internal": "INTERNAL_ERROR",
        "deadline_exceeded": "TIMEOUT_ERROR",
    }
    
    def normalize_capability(
        self,
        remote_tool_name: str,
        remote_capability: dict[str, Any],
        metadata,
    ) -> CapabilityContract:
        """Normalize Google Workspace capability to anticafarmacia format."""
        
        # Extract service category (gmail, drive, sheets, docs)
        service_category = remote_tool_name.split("_")[0]  # e.g., "gmail_send_message" → "gmail"
        
        # Call parent normalization
        contract = super().normalize_capability(remote_tool_name, remote_capability, metadata)
        
        # Apply Google Workspace-specific customizations
        contract.routing_hints["service"] = service_category
        contract.routing_hints["category"] = self.CATEGORY_MAPPING.get(service_category, "general")
        
        # Add Google-specific documentation
        contract.routing_hints["google_api_endpoint"] = remote_capability.get("google_api_endpoint")
        contract.routing_hints["google_required_scopes"] = remote_capability.get("required_scopes", [])
        
        return contract
    
    def adapt_auth_requirements(
        self,
        contract: CapabilityContract,
        downstream_auth_config: dict[str, Any],
    ) -> CapabilityContract:
        """Adapt Google Workspace auth to anticafarmacia OAuth 2.1."""
        
        if not downstream_auth_config:
            return contract
        
        # Map Google scopes to anticafarmacia scopes
        google_scopes = downstream_auth_config.get("scopes", [])
        adapted_scopes = []
        
        for google_scope in google_scopes:
            adapted_scope = self.SCOPE_MAPPING.get(
                google_scope,
                f"anticafarmacia:federated:google_workspace:custom.{google_scope}"
            )
            adapted_scopes.append(adapted_scope)
        
        contract.required_scopes = tuple(adapted_scopes)
        
        # Document auth requirements for gateway
        contract.routing_hints["google_auth_type"] = downstream_auth_config.get("type", "oauth2")
        contract.routing_hints["google_scopes"] = google_scopes
        contract.routing_hints["auth_requires_user_consent"] = True
        
        # Set auth profile based on scope requirements
        if "admin" in str(google_scopes):
            contract.auth_profile = "admin"
        elif "write" in str(google_scopes):
            contract.auth_profile = "service"
        else:
            contract.auth_profile = "user"
        
        return contract
    
    def adapt_error_normalization(
        self,
        contract: CapabilityContract,
        remote_error_mapping: dict[str, str] | None = None,
    ) -> CapabilityContract:
        """Adapt Google Workspace error codes to anticafarmacia format."""
        
        contract.routing_hints["error_mapping"] = self.ERROR_MAPPING
        
        return contract
```

### Discovery at Startup

```python
# File: artifacts/skill_federation_integration.py (updated)

from .skill_normalizers import get_normalizer

async def initialize_federated_skills(mcp, client, settings):
    """Initialize with domain-specific normalizers."""
    registry = FederatedSkillRegistry(cache_ttl_seconds=settings.cache_ttl or 3600)
    
    if not settings.gateway.remotes:
        return registry
    
    for remote in settings.gateway.remotes:
        if not remote.enabled:
            continue
        
        try:
            async with RemoteMCPIntrospector(remote.name, remote.url, remote.auth) as introspector:
                capabilities = await introspector.discover_capabilities()
                
                # Get domain-specific normalizer
                normalizer = get_normalizer(remote.name, remote.namespace)
                
                for tool_name, capability in capabilities.items():
                    metadata = RemoteCapabilityMetadata(...)
                    
                    # Use domain-specific normalization
                    contract = normalizer.normalize_capability(tool_name, capability, metadata)
                    contract = normalizer.adapt_auth_requirements(contract, capability.get("auth_config"))
                    contract = normalizer.adapt_error_normalization(contract)
                    
                    # Register skill
                    skill = FederatedSkillInfo(...)
                    registry.register_skill(skill, metadata)
        
        except Exception as e:
            logger.error(f"Failed skill discovery for {remote.name}: {e}")
    
    return registry
```

## Example 2: Skill Proxy Implementation

### Gmail Send Message Proxy

```python
# File: artifacts/apps/federated_skills.py

from fastmcp import FastMCP
from typing import Any
import httpx

async def create_gmail_send_proxy(mcp: FastMCP, registry, client, settings):
    """Create a local tool proxy for google_workspace_mcp.gmail_send_message"""
    
    skill = registry.get_skill("federated.google_workspace.gmail_send_message")
    if not skill:
        return
    
    @mcp.tool(
        name="federated_google_workspace_gmail_send_message",
        description=skill.description,
    )
    async def gmail_send_message(
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an email via Gmail API.
        
        This is a skill federated from google_workspace_mcp.
        """
        
        # 1. Build routing request
        routing_request = {
            "arguments": {
                "to": to,
                "subject": subject,
                "body": body,
                "cc": cc,
                "bcc": bcc,
                "reply_to": reply_to,
            },
            "routing_hints": skill.canonical_contract.routing_hints,
        }
        
        # 2. Route through gateway with auth adaptation
        try:
            # Get remote MCP endpoint
            remote_mcp_url = skill.canonical_contract.routing_hints.get("remote_url")
            google_scopes = skill.canonical_contract.routing_hints.get("google_scopes", [])
            
            # Build call to remote MCP
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(
                    f"{remote_mcp_url}/tools/{skill.remote_tool_name}",
                    json=routing_request["arguments"],
                    headers={
                        "Authorization": f"Bearer {settings.google_workspace_mcp_token}",
                        "X-Anticafarmacia-Original-Scopes": ",".join(google_scopes),
                        "X-Anticafarmacia-Skill-ID": skill.skill_id,
                    },
                    timeout=30.0,
                )
            
            # 3. Normalize response
            if response.status_code == 200:
                result = response.json()
                
                # Ensure consistent response format
                return {
                    "message_id": result.get("message_id"),
                    "timestamp": result.get("timestamp"),
                    "status": "sent",
                    "_skill_metadata": {
                        "skill_id": skill.skill_id,
                        "remote_mcp": skill.remote_mcp,
                        "scopes_used": google_scopes,
                    }
                }
            else:
                # 4. Adapt errors
                error_code = response.json().get("error", {}).get("code")
                error_mapping = skill.canonical_contract.routing_hints.get("error_mapping", {})
                anticafarmacia_error = error_mapping.get(error_code, "PROVIDER_ERROR")
                
                raise Exception(
                    f"Gmail API error ({anticafarmacia_error}): "
                    f"{response.json().get('error', {}).get('message')}"
                )
        
        except httpx.TimeoutException:
            raise Exception("Gmail operation timed out (TIMEOUT_ERROR)")
        except httpx.RequestError as e:
            raise Exception(f"Network error calling Gmail API (TRANSIENT_ERROR): {e}")
```

### Drive Operations Proxy

```python
# File: artifacts/apps/federated_skills.py (continued)

async def create_drive_proxies(mcp: FastMCP, registry, client, settings):
    """Create local tool proxies for Google Drive skills"""
    
    drive_skills = [
        s for s in registry.get_all_skills()
        if s.remote_mcp == "google_workspace_mcp" and "drive" in s.remote_tool_name
    ]
    
    for skill in drive_skills:
        # Create factory function to avoid closure issues
        def make_drive_tool(skill_obj):
            @mcp.tool(
                name=skill_obj.local_tool_name,
                description=skill_obj.description,
            )
            async def drive_tool(**kwargs) -> dict[str, Any]:
                """Route Drive operation to google_workspace_mcp via gateway."""
                
                # Generic drive routing implementation
                return {
                    "status": "routed",
                    "skill_id": skill_obj.skill_id,
                    "remote_mcp": skill_obj.remote_mcp,
                    "operation": skill_obj.remote_tool_name,
                    "arguments": kwargs,
                    # In production: actual call to remote MCP
                }
            
            return drive_tool
        
        mcp.tool()(make_drive_tool(skill))
```

## Example 3: Client Usage Patterns

### Pattern 1: Direct Skill Invocation

```python
# Claude or other upstream client invokes federated skill directly

# Query available skills
POST /tools/list_federated_skills
{
  "filter_by_remote_mcp": "google_workspace_mcp",
  "filter_by_category": "communication"
}

# Invokes skill
POST /tools/federated_google_workspace_gmail_send_message
{
  "to": "user@example.com",
  "subject": "Meeting Tomorrow",
  "body": "Let's meet at 3pm"
}

# Response
{
  "message_id": "123abc",
  "timestamp": "2026-08-19T14:30:00Z",
  "status": "sent",
  "_skill_metadata": {
    "skill_id": "federated.google_workspace.gmail_send_message",
    "remote_mcp": "google_workspace_mcp"
  }
}
```

### Pattern 2: Skill Composition

```python
# Claude composes multiple federated skills in sequence

# 1. Create a Google Doc
POST /tools/federated_google_workspace_docs_create
{
  "title": "Meeting Notes - 2026-08-19"
}
→ {"document_id": "doc123", "url": "https://docs.google.com/document/d/doc123"}

# 2. Write content to the Doc
POST /tools/federated_google_workspace_docs_append
{
  "document_id": "doc123",
  "content": "## Topics Discussed\n1. Q3 planning\n2. Team retrospective"
}

# 3. Share the Doc
POST /tools/federated_google_workspace_drive_share
{
  "file_id": "doc123",
  "email": "team@example.com",
  "role": "viewer"
}

# 4. Send email with link
POST /tools/federated_google_workspace_gmail_send_message
{
  "to": "team@example.com",
  "subject": "Meeting Notes",
  "body": "See the notes here: https://docs.google.com/document/d/doc123"
}

# Result: Multi-step workflow using federated skills from google_workspace_mcp
```

### Pattern 3: Skill Introspection

```python
# Query skill registry resource
GET /resource/anticafarmacia://skills/federated/registry

# Response includes full capability details
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
      "local_tool_name": "federated_google_workspace_gmail_send_message",
      "remote_mcp": "google_workspace_mcp",
      "remote_tool_name": "gmail_send_message",
      "title": "Send Gmail Message",
      "description": "Send an email via Gmail API",
      "category": "communication",
      "requires_auth": true,
      "auth_scopes": [
        "anticafarmacia:federated:google_workspace:email.send"
      ],
      "reliability_tier": "tier_a",
      "pii_classification": "high"
    },
    ...
  ]
}
```

## Example 4: Server Integration

### Updated server.py

```python
# File: server.py

from artifacts.skill_federation_integration import (
    initialize_federated_skills,
    create_skill_federation_summary_tool,
)

async def create_mcp():
    """Create and configure FastMCP server with federated skills."""
    
    mcp = FastMCP("AnticaFarmacia MCP")
    client = AnticaFarmaciaRestClient(settings)
    
    # 1. Load local artifacts
    local_tool_registry, local_resources = await artifacts.tools.local.register_local_tools(
        mcp, client, settings, ...
    )
    
    # 2. Initialize federated skill discovery
    federated_registry = await initialize_federated_skills(mcp, client, settings)
    
    logger.info(
        f"MCP initialized with {len(local_tool_registry)} local tools "
        f"and {len(federated_registry.get_all_skills())} federated skills"
    )
    
    # 3. Register skill discovery/listing tool
    create_skill_federation_summary_tool(mcp, federated_registry)
    
    # 4. Store registry for middleware access
    mcp._federated_registry = federated_registry
    
    return mcp, federated_registry
```

### Docker Compose Configuration

```yaml
# docker-compose.yml snippet

services:
  anticafarmacia-mcp:
    environment:
      # Remote MCPs to discover skills from
      ANTICAFARMACIA_GATEWAY_REMOTES_JSON: |
        [
          {
            "name": "google-workspace-mcp",
            "namespace": "google_workspace",
            "type": "streamable-http",
            "url": "https://workspace.dchat.ditra.app/mcp",
            "auth": "Bearer ${GOOGLE_WORKSPACE_MCP_TOKEN}",
            "initTimeout": 20000,
            "timeout": 60000,
            "serverInstructions": true,
            "enabled": true
          },
          {
            "name": "google-toolbox-mcp",
            "namespace": "google_toolbox",
            "type": "streamable-http",
            "url": "http://google-toolbox-mcp:8000/mcp",
            "auth": "Bearer ${GOOGLE_TOOLBOX_MCP_TOKEN}",
            "enabled": true
          }
        ]
```

## Testing Federated Skills

### Unit Test: Skill Normalization

```python
# tests/test_skill_federation.py

import pytest
from artifacts.skill_normalizers import GoogleWorkspaceNormalizer

def test_gmail_skill_normalization():
    """Test normalization of Gmail send skill."""
    
    normalizer = GoogleWorkspaceNormalizer("google_workspace_mcp", "google_workspace")
    
    remote_capability = {
        "capability_id": "gmail.send_message",
        "tool_name": "gmail_send_message",
        "description": "Send an email via Gmail API",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
            },
        },
        "auth_profile": "service",
        "required_scopes": ["gmail.send"],
        "reliability_tier": "tier_a",
        "error_categories": ["AUTH_ERROR", "RATE_LIMIT_ERROR"],
        "pii_classification": "high",
    }
    
    metadata = RemoteCapabilityMetadata(
        remote_mcp_name="google_workspace_mcp",
        remote_namespace="google_workspace",
        remote_tool_name="gmail_send_message",
        discovered_at=time.time(),
        discovery_source="capability_registry",
    )
    
    # Normalize
    contract = normalizer.normalize_capability("gmail_send_message", remote_capability, metadata)
    
    # Assertions
    assert contract.capability_id == "federated.google_workspace.gmail_send_message"
    assert contract.tool_name == "federated_google_workspace_gmail_send_message"
    assert "anticafarmacia:federated:google_workspace:email.send" in contract.required_scopes
    assert contract.reliability_tier == "tier_a"
    assert contract.pii_classification == "high"
    assert contract.provider == "google_workspace_mcp"
    assert contract.is_local == False
```

### Integration Test: Federated Skill Discovery

```python
# tests/test_skill_federation_integration.py

@pytest.mark.asyncio
async def test_federated_skill_discovery():
    """Test end-to-end skill discovery from mock google_workspace_mcp."""
    
    # Mock remote MCP capability registry
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://mock.google_workspace_mcp/capability/registry",
            json={
                "gmail_send_message": {
                    "capability_id": "gmail.send_message",
                    "tool_name": "gmail_send_message",
                    # ...full capability dict...
                },
            },
            status=200,
        )
        
        # Initialize discovery
        registry = FederatedSkillRegistry()
        summary = await load_federated_skills(registry, settings)
        
        # Assertions
        assert summary["total_skills_normalized"] == 1
        assert len(registry.get_all_skills()) == 1
        
        skill = registry.get_skills_from_mcp("google_workspace_mcp")[0]
        assert skill.skill_id == "federated.google_workspace.gmail_send_message"
        assert skill.remote_mcp == "google_workspace_mcp"
```

## Troubleshooting

### Skill Discovery Fails

```python
# Check logs
docker logs anticafarmacia-mcp | grep "Skill discovery"

# Verify remote MCP is accessible
curl https://workspace.dchat.ditra.app/mcp/capability/registry \
  -H "Authorization: Bearer $TOKEN"

# Check configuration
echo $ANTICAFARMACIA_GATEWAY_REMOTES_JSON | jq .
```

### Skills Not Appearing

```python
# List registered skills programmatically
POST /tools/list_federated_skills
{}

# Query resource
GET /resource/anticafarmacia://skills/federated/registry

# Check registry cache TTL
echo $ANTICAFARMACIA_CACHE_TTL  # default 3600s
```

### Skill Invocation Fails

```python
# Enable debug logging
export LOG_LEVEL=DEBUG

# Check skill routing hints
GET /resource/anticafarmacia://skills/federated/registry
# Look for "routing_hints" in response

# Verify remote auth token
echo $GOOGLE_WORKSPACE_MCP_TOKEN | jq .
```
