# Skill Federation Quick Start

Get federated skills from google_workspace_mcp visible and usable via anticafarmacia_mcp in 5 steps.

## Step 1: Verify Remote MCP Accessibility

```bash
# Check if google_workspace_mcp is running and accessible
curl -v https://workspace.dchat.ditra.app/mcp/capability/registry \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json"

# Expected response: JSON dict with capability IDs as keys
# {"gmail_send_message": {...}, "drive_upload": {...}, ...}
```

## Step 2: Configure anticafarmacia_mcp Gateway

Update your `.env` or `docker-compose.yml`:

```bash
export ANTICAFARMACIA_GATEWAY_REMOTES_JSON='[
  {
    "name": "google-workspace-mcp",
    "namespace": "google_workspace",
    "type": "streamable-http",
    "url": "https://workspace.dchat.ditra.app/mcp",
    "auth": "Bearer YOUR_GOOGLE_WORKSPACE_TOKEN",
    "initTimeout": 20000,
    "timeout": 60000,
    "serverInstructions": true,
    "enabled": true
  }
]'

# Or in docker-compose.yml:
# environment:
#   ANTICAFARMACIA_GATEWAY_REMOTES_JSON: '[...]'
```

## Step 3: Enable Federated Skill Discovery

Update `server.py` to initialize skill discovery at startup:

```python
# In server.py (around line where mcp is created)

from artifacts.skill_federation_integration import (
    initialize_federated_skills,
    create_skill_federation_summary_tool,
)

async def create_mcp():
    mcp = FastMCP("AnticaFarmacia MCP")
    client = AnticaFarmaciaRestClient(settings)
    
    # ... existing setup ...
    
    # NEW: Initialize federated skill discovery
    federated_registry = await initialize_federated_skills(mcp, client, settings)
    
    # NEW: Create skill listing tool for clients
    create_skill_federation_summary_tool(mcp, federated_registry)
    
    # Store registry for later reference
    mcp._federated_registry = federated_registry
    
    return mcp
```

## Step 4: Start Server

```bash
# Via Docker
docker-compose up -d anticafarmacia-mcp

# Or via Python
python -m anticafarmacia_mcp

# Check logs for skill discovery
docker logs anticafarmacia-mcp | grep -i "skill discovery"

# Expected output:
# INFO: Starting federated skill discovery for 1 remote MCPs
# INFO: Discovered 25 capabilities from google-workspace-mcp via /capability/registry
# INFO: Registered 25 federated skills
# INFO: Federated skill discovery complete: 25 skills normalized
```

## Step 5: Query Federated Skills

### Method 1: List Available Skills

```bash
curl -X POST http://localhost:8001/tools/list_federated_skills \
  -H "Content-Type: application/json" \
  -d '{
    "filter_by_remote_mcp": "google_workspace_mcp"
  }'

# Response:
{
  "total_available": 25,
  "skills": [
    {
      "skill_id": "federated.google_workspace.gmail_send_message",
      "title": "Send Gmail Message",
      "description": "Send an email via Gmail API",
      "category": "communication",
      "remote_mcp": "google_workspace_mcp",
      "local_tool_name": "federated_google_workspace_gmail_send_message",
      "requires_auth": true
    },
    {
      "skill_id": "federated.google_workspace.drive_upload_file",
      "title": "Upload File to Google Drive",
      "category": "storage",
      ...
    },
    ...
  ]
}
```

### Method 2: Inspect Skill Registry

```bash
curl http://localhost:8001/resource/anticafarmacia://skills/federated/registry \
  -H "Accept: application/json"

# Response:
{
  "schema_version": "1.0",
  "registry_type": "federated",
  "timestamp": 1692475200,
  "summary": {
    "total_skills": 25,
    "by_remote_mcp": {
      "google_workspace_mcp": 25
    }
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
      "auth_scopes": [
        "anticafarmacia:federated:google_workspace:email.send"
      ],
      "reliability_tier": "tier_a",
      "pii_classification": "high"
    },
    ...
  ],
  "discovery_status": {
    "mcps_queried": ["google-workspace-mcp"],
    "errors": {}
  }
}
```

### Method 3: Use Skill Directly (Claude/Upstream Client)

```bash
# Invoke federated Gmail skill directly
curl -X POST http://localhost:8001/tools/federated_google_workspace_gmail_send_message \
  -H "Content-Type: application/json" \
  -d '{
    "to": "user@example.com",
    "subject": "Hello from anticafarmacia_mcp",
    "body": "This email was sent via a federated skill from google_workspace_mcp"
  }'

# Response:
{
  "message_id": "1234567890abcdef",
  "timestamp": "2026-08-19T14:30:00Z",
  "status": "sent",
  "_skill_metadata": {
    "skill_id": "federated.google_workspace.gmail_send_message",
    "remote_mcp": "google_workspace_mcp"
  }
}
```

## Verification Checklist

- [ ] `ANTICAFARMACIA_GATEWAY_REMOTES_JSON` is set correctly
- [ ] Remote MCP URL is accessible from anticafarmacia_mcp container
- [ ] Bearer token for remote MCP is valid
- [ ] Server logs show successful skill discovery (0 errors)
- [ ] `list_federated_skills` tool returns skills
- [ ] `anticafarmacia://skills/federated/registry` resource is accessible
- [ ] Can invoke at least one federated skill successfully

## Common Issues & Fixes

### Issue: No Skills Discovered

```bash
# 1. Check remote MCP accessibility
curl https://workspace.dchat.ditra.app/mcp/capability/registry \
  -H "Authorization: Bearer $TOKEN"

# 2. Check logs
docker logs anticafarmacia-mcp | grep -i "skill discovery\|error"

# 3. Verify configuration
docker exec anticafarmacia-mcp env | grep ANTICAFARMACIA_GATEWAY_REMOTES

# 4. Restart server
docker-compose restart anticafarmacia-mcp
```

### Issue: Skills Not Appearing in `list_federated_skills`

```bash
# 1. Check registry is populated
curl http://localhost:8001/resource/anticafarmacia://skills/federated/registry | jq '.summary.total_skills'

# 2. Check if server has the tool registered
curl http://localhost:8001/tools | jq '.[].name' | grep federated

# 3. Verify skill_federation_integration.py is imported in server.py
grep -r "skill_federation_integration" servers/anticafarmacia_mcp/server.py
```

### Issue: Skill Invocation Fails

```bash
# 1. Verify skill exists
curl http://localhost:8001/resource/anticafarmacia://skills/federated/registry | \
  jq '.skills[] | select(.skill_id == "federated.google_workspace.SKILL_NAME")'

# 2. Check auth token is still valid
# Contact google_workspace_mcp provider for token refresh

# 3. Check skill input schema
curl http://localhost:8001/resource/anticafarmacia://skills/federated/registry | \
  jq '.skills[] | select(.skill_id == "federated.google_workspace.gmail_send_message")'

# 4. Enable debug logging
export LOG_LEVEL=DEBUG
docker-compose restart anticafarmacia-mcp
docker logs anticafarmacia-mcp -f
```

## Next: Advanced Patterns

Once basic skill federation is working, explore:

1. **Skill Composition**: Combine multiple federated skills in workflows
2. **Error Adaptation**: Handle failures gracefully with retry logic
3. **Auth Bridging**: Map google_workspace auth scopes to upstream OAuth 2.1
4. **Skill Caching**: Customize cache TTL for frequently-used skills
5. **Metrics**: Add Prometheus metrics for skill usage, latency, errors
6. **Multi-MCP**: Federate skills from multiple remote MCPs (google_toolbox, etc.)

## Documentation References

- **Architecture**: [SKILL_FEDERATION.md](SKILL_FEDERATION.md)
- **Examples**: [SKILL_FEDERATION_EXAMPLES.md](SKILL_FEDERATION_EXAMPLES.md)
- **Implementation**: [artifacts/skill_federation.py](artifacts/skill_federation.py)
- **Integration**: [artifacts/skill_federation_integration.py](artifacts/skill_federation_integration.py)
- **Skills Reference**: [SKILLS_INTEGRATION.md](SKILLS_INTEGRATION.md)

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review [SKILL_FEDERATION_EXAMPLES.md](SKILL_FEDERATION_EXAMPLES.md) for detailed examples
3. Enable debug logging and check server logs
4. Verify gateway configuration: `echo $ANTICAFARMACIA_GATEWAY_REMOTES_JSON | jq .`
5. Test remote MCP connectivity directly (curl command above)
