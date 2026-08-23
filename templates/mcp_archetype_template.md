# MCP Archetype Template

Use this template as the source of truth for all MCP repositories.

## 1. Identity
- mcp_name:
- mcp_role: master | domain | integration | utility
- business_domain:
- owners:
- version:

## 2. Context Plane
- tenant_resolution_strategy:
- policy_sources:
- compliance_tags:
- data_classification:

## 3. Capability Plane

### 3.1 Capability Registry
List canonical capabilities:

```yaml
capabilities:
  - capability_id:
    display_name:
    version:
    input_schema_ref:
    output_schema_ref:
    aliases: {}
    error_categories: []
    auth_profile:
    reliability_tier: tier_a|tier_b|tier_c
    fallback_mode: none|local_alternative|cached_readonly
```

### 3.2 Discovery Tools
- gateway_discover_capabilities
- gateway_get_capability_schema
- gateway_validate_capability_input
- gateway_capability_health

## 4. Connector Plane
- downstream_mcps:
- direct_integrations:
- adapter_modules:
- timeout_policy:
- retry_policy:
- circuit_breaker_policy:

## 5. Auth Model
- inbound_auth_mode:
- outbound_auth_mode:
- token_store:
- refresh_policy:
- dpop_enabled:

## 6. FastMCP Runtime Defaults
- stateless_http: true
- host_origin_protection: true
- protocol_mode: auto
- oauth_mount_invariant_validated: true
- eventstore_strategy_defined: true

## 7. Observability
- request_id_standard:
- structured_logging_fields:
- audit_event_types:
- service_level_indicators:

## 8. Diagnostics
- auth_status_tool: required
- auth_recover_tool: required
- provider_health_tool: required
- policy_explain_tool: required

## 9. Tests
- contract_tests:
- adapter_tests:
- workflow_tests:
- smoke_tests:

## 10. Onboarding Gate
- template_compliance: pass|fail
- capability_contract_lint: pass|fail
- error_taxonomy_check: pass|fail
- auth_profile_validation: pass|fail
- master_smoke_test: pass|fail

## 11. Repo Layout Check
Expected folders:
- capability/
- adapters/
- orchestration/
- gateway/
- observability/
- tools/
- tests/
- docs/
