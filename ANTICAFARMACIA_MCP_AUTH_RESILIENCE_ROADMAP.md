# Anticafarmacia MCP Auth Resilience Roadmap

**Date**: 2026-08-17  
**Scope**: Gateway auth robustness, health signaling, token lifecycle persistence  
**Owner**: Coding Agent  

---

## Tier 1: Blocking Production Stability

### Task 1.0: Local-First MCP Resilience (Gateway Isolation)
**Issue**: When downstream gateway backends fail, tools/prompts/resources/apps from local providers are blocked or degraded.

**Code Areas**:
- `servers/anticafarmacia_mcp/server.py` (register_local_tools, register_local_prompts, register_local_resources, create_local_app_providers)
- `servers/anticafarmacia_mcp/providers/` (all local_*.py)
- `servers/anticafarmacia_mcp/gateway/aggregate.py` (if exists, provider aggregation)

**Acceptance Criteria**:
1. Local tools/prompts/resources are registered and reachable even when ALL remotes are down.
2. RemoteProvider failures (gateway timeout, 500, auth error) do NOT prevent local tools from being listed or called.
3. Error isolation:
   - Remote tool list failure → log WARN, skip that remote's tools from aggregation; local and other remotes remain available.
   - Remote tool call failure → return clear error indicating remote failure; do not cascade to local tool registry.
4. `tools/list` always returns local tools with status indicating which remotes succeeded/failed:
   ```json
   {
     "tools": [
       { "name": "local_auth_debug", "description": "...", "source": "local" },
       { "name": "gateway_list_remote_tools", "description": "...", "source": "local" },
       { "name": "google_workspace_list_tools", "source": "remote", "remote_name": "google-workspace-mcp", "available": false, "error": "circuit open" }
     ]
   }
   ```
5. Remote operations (list_tools, tool calls) use non-blocking async with per-remote timeout (default: 10s):
   - Timeout expired → circuit breaker activates; local tools unaffected.
   - Remote slow → upstream caller gets timeout, can retry; local tools available immediately.
6. Unit test: kill all remotes, verify local tools are callable and aggregated response includes remote failure info.
7. Load test: spike latency on one remote to >10s, verify other remotes and local tools remain responsive.

**Estimated Effort**: 3-4h

---

### Task 1.1: Refresh Token Rotation Persistence + Atomic Updates
**Issue**: Refresh token from endpoint is not persisted; stale in-memory token causes `invalid_grant` failures.

**Code Areas**:
- `servers/anticafarmacia_mcp/gateway/remote_auth.py:145-196`
- `servers/anticafarmacia_mcp/settings.py` (env parsing)

**Acceptance Criteria**:
1. When token endpoint returns new `refresh_token` in response, it is atomically persisted to `.env` (or equiv. durable store).
2. Subsequent refresh cycles use the updated token.
3. No race conditions: concurrent refresh requests serialize safely.
4. Token update failures are logged with context; service does not retry stale token.
5. Unit test: mock endpoint returning rotated `refresh_token`, verify persistence and subsequent call succeeds.

**Estimated Effort**: 2-3h  

---

### Task 1.2: Auth Failure Circuit Breaker + Backoff
**Issue**: Repeated 401/invalid_token/invalid_grant failures cause retry storms in logs.

**Code Areas**:
- `servers/anticafarmacia_mcp/gateway/direct.py` (call_remote_tool_direct, list_remote_tools)
- `servers/anticafarmacia_mcp/gateway/remote_auth.py` (resolve_remote_auth_sync)

**Acceptance Criteria**:
1. Detect auth-specific errors: `invalid_token`, `invalid_grant`, `401`, `403`.
2. After N consecutive auth failures (default: 3), enter "auth degraded" state per remote.
3. In degraded state:
   - Stop active calls to that remote; return clear error explaining degradation.
   - Reject new refresh attempts for cooldown window (default: 5 min).
   - Log degradation entry/exit at WARN level.
4. Expose degradation state via readiness/status endpoint (see Task 1.3).
5. Admin endpoint to manually clear degradation if needed.
6. Unit test: simulate N 401 responses; verify circuit opens, tool calls rejected, status reflects degradation.

**Estimated Effort**: 2-3h  

---

### Task 1.3: Split Health into Liveness + Readiness + Dependency Status
**Issue**: `/health` returns 200 while auth is broken; callers can't distinguish process-up from auth-operational.

**Code Areas**:
- `servers/anticafarmacia_mcp/server.py:475-490` (readiness_check, health_check endpoints)

**Acceptance Criteria**:
1. Keep `/health` lightweight (process + basic startup checks).
2. Add `/ready` (existing) to include:
   - Inbound auth readiness (OIDC discovery reachable).
   - Required remotes reachable (connect timeout check, not full tool list).
   - At least one auth path working (inbound OR a prioritized outbound remote).
3. Add new `/status` endpoint returning JSON:
   ```json
   {
     "status": "ready|degraded|unhealthy",
     "liveness": true,
     "auth": {
       "inbound_oidc_reachable": bool,
       "outbound_remotes": [
         { "name": "google-workspace-mcp", "healthy": bool, "last_auth_error": "...", "degraded_until": "ISO8601 or null" }
       ]
     }
   }
   ```
4. Integration test: simulate remote auth failure; verify `/health` still 200, `/ready` 503, `/status` shows degradation.

**Estimated Effort**: 2h  

---

## Tier 2: Resilience + Observability

### Task 2.1: Automated Recovery Ladder + Admin Status Endpoint
**Issue**: Manual remediation needed when refresh token is revoked.

**Code Areas**:
- `servers/anticafarmacia_mcp/gateway/remote_auth.py` (resolve_remote_auth_sync, enable_dpop_for_remote_auth)
- `servers/anticafarmacia_mcp/server.py` (custom endpoints)

**Acceptance Criteria**:
1. Add `@mcp.tool()` endpoint: `gateway_remote_auth_status(remote_name: str | None)` returning:
   - Last auth error + timestamp
   - Last successful refresh + timestamp
   - Refresh attempt count (current cycle)
   - Circuit breaker state (open/closed) + cooldown remaining
2. Add helper tool: `gateway_remote_trigger_rebootstrap(remote_name: str, force: bool = false)` that:
   - Clears cached tokens for that remote.
   - If `force=true`, clears circuit breaker state.
   - Returns status of prepared state for OAuth re-flow (e.g., "ready for bootstrap_gateway_oauth.sh").
3. Document remediation path: when `invalid_grant` persists, operator runs bootstrap flow and re-enables remote.
4. Add debug logs showing why each recovery step succeeded/failed.
5. Integration test: simulate revoked token, verify status tool reports it, trigger rebootstrap, verify recovery readiness.

**Estimated Effort**: 2-3h  

---

### Task 2.2: Token Cache Jitter + Concurrency Safety
**Issue**: Token cache refresh timing can synchronize, creating bursts under load.

**Code Areas**:
- `servers/anticafarmacia_mcp/gateway/remote_auth.py:130-135` (_put_cached_token, TTL logic)
- `servers/anticafarmacia_mcp/gateway/direct.py` (concurrent calls to list_remote_tools, etc.)

**Acceptance Criteria**:
1. Implement jittered refresh: when TTL expires, add random jitter (0-30% of TTL) before next refresh.
2. Use asyncio.Lock or similar to serialize per-remote token refresh; multiple concurrent callers wait on same refresh, not duplicate.
3. If refresh fails, use exponential backoff for retry (1s, 2s, 4s, 8s) within cooldown window (see Task 1.2).
4. Unit test: multiple concurrent threads requesting token; verify only one refresh issued, all get same token.
5. Load test: 100 concurrent tool calls; verify no token endpoint rate-limit errors from burst.

**Estimated Effort**: 2h  

---

### Task 2.3: Auth Isolation Policy + Startup Diagnostics
**Issue**: Inbound/outbound auth are code-separate but operationally coupled; unclear failure domains.

**Code Areas**:
- `servers/anticafarmacia_mcp/oauth.py:121` (inbound OIDC)
- `servers/anticafarmacia_mcp/gateway/remote_auth.py:72` (outbound)
- `servers/anticafarmacia_mcp/settings.py` (all config)

**Acceptance Criteria**:
1. Document policy:
   - Inbound identity (OIDC client_id, GCIP api_key) is for anticafarmacia user authentication.
   - Outbound identity (refresh_token, client_secret for each remote) is service-level delegation, NOT per-user.
   - Failure domains are separate: inbound OIDC down ≠ outbound remote down.
2. Add startup diagnostic logging (info level):
   ```
   Inbound auth configured: OIDC [discovery_url], GCIP [api_key_set=true/false], PKCE [enabled]
   Outbound remotes: google-workspace-mcp [auth=refresh_token], ...
   Identity sharing: inbound and outbound are [distinct/shared via CLIENT_ID] (document risk if shared).
   ```
3. If inbound and outbound use same OIDC client_id, log WARNING with remediation guidance.
4. Startup test: verify diagnostic output in logs, check warning condition detection.

**Estimated Effort**: 1h  

---

## Tier 3: Tech Debt

### Task 3.1: Plan Migration from authlib.jose to joserfc
**Issue**: Runtime deprecation warning from authlib.jose usage.

**Code Areas**:
- `servers/anticafarmacia_mcp/oauth.py:29` (import authlib.jose)

**Acceptance Criteria**:
1. Audit all authlib.jose usage in oauth.py (JWT decode, signing, etc.).
2. Create migration plan document:
   - Which functions use deprecated path.
   - Equivalent joserfc or updated authlib API.
   - Compatibility matrix (Python versions, dep versions).
3. Implement migration (if time permits) or open follow-up task.
4. Verify no deprecation warnings in startup logs.
5. Test JWT validation path still works after migration.

**Estimated Effort**: 1-2h (plan); 2-3h (implementation if included)  

---

### Task 3.2: Refresh Token Revocation Recovery Runbook
**Issue**: When refresh token is revoked upstream, no clear self-service path to recover.

**Acceptance Criteria**:
1. Add `.env` comments documenting the refresh-revocation boundary:
   ```
   # Refresh token lifecycle:
   # - Initially obtained via: ./bootstrap_gateway_oauth.sh
   # - Auto-rotated by server when new token received from token endpoint.
   # - Revoked upstream (e.g., user logged out) → invalid_grant
   # - Recovery: re-run bootstrap flow for that remote.
   ```
2. Create or update `docs/GATEWAY_AUTH_TROUBLESHOOTING.md`:
   - Symptom: `invalid_grant` in logs.
   - Root cause: refresh token revoked or invalid.
   - Steps:
     1. Verify remote is in `enabled: true` state.
     2. Run `./bootstrap_gateway_oauth.sh` and complete OAuth flow.
     3. Run `./refresh_gateway_token.sh` to test.
     4. Restart service: `docker compose up -d --force-recreate`.
3. Link runbook in startup health check output if degradation detected.

**Estimated Effort**: 0.5h  

---

## Test Plan Summary

**Unit Tests** (per-function mocking):
- Token refresh with rotation persistence
- Circuit breaker state transitions
- Cache jitter + concurrency
- Auth failure detection and logging

**Integration Tests** (with mock remote endpoints):
- Full auth failure -> degradation -> recovery cycle
- `/ready` and `/status` endpoints reflect real states
- Concurrent token refresh serialization

**Load/Stress Tests**:
- 100+ concurrent tool calls during token rotation
- Auth failure bursts do not overwhelm retry logic

**Manual/Acceptance Tests**:
- Revoke upstream refresh token, verify logs and `/status`, run recovery ladder
- Verify startup diagnostic logging for identity config
- Verify no deprecation warnings on Python 3.12+

---

## Implementation Order

1. **Task 1.0** (Local-first isolation) — ensures MCP survives gateway outages; all other tasks depend on this foundation
2. **Task 1.1** (Token persistence) — blocks everything downstream
3. **Task 1.2** (Circuit breaker) — prevents retry storms; builds on 1.0 isolation
4. **Task 1.3** (Readiness/Status endpoints) — enables observability of local + remote health
5. **Task 2.1** (Recovery ladder) — enables self-service remediation
6. **Task 2.2** (Cache jitter) — improves stability under load; compatible with 1.0 async design
7. **Task 2.3** (Auth isolation policy) — reduces cognitive load for ops
8. **Task 3.1** (joserfc migration) — removes deprecation warnings
9. **Task 3.2** (Runbook) — improves operational clarity; references 1.0 fallback behavior

**Total Estimated Time**: 17-23 hours (includes 3-4h for new Task 1.0)  
**Recommended Parallelization**: 
1. Task 1.0 alone (foundation)
2. Tasks 1.1 + 1.2 in parallel (auth resilience)
3. Task 1.3 (observability)
4. Tasks 2.1 + 2.2 in parallel (recovery + caching)
5. Tasks 2.3 + 3.1 + 3.2 in parallel (cleanup + docs)

---

## Success Metrics

- [ ] **Local MCP Resilience**: All local tools/prompts/resources remain callable when ALL remotes are down (100% availability)
- [ ] **Gateway Isolation**: Remote tool list failure does NOT cascade to local tools; `tools/list` always returns local + error status for failed remotes
- [ ] **Timeout Safety**: Remote operations timeout at 10s; local tool response time <500ms unaffected by remote slowness
- [ ] **No `invalid_grant` retry storms** in logs for 7 days post-deployment
- [ ] **Circuit breaker** prevents >50% of auth-induced tool call timeouts
- [ ] **`/status` endpoint** reliably reflects local + per-remote health state within 30s of change
- [ ] **Manual recovery runbook** tested by operator; recovery time <5 min
- [ ] **Zero deprecation warnings** in startup logs
- [ ] **Auth isolation policy** documented; misaligned identity sharing detected at startup
- [ ] **Load test pass**: 100 concurrent tool calls during single remote failure; local tools maintain <100ms p99 latency

---

## Architectural Patterns for Gateway Resilience

### 1. Local-First Aggregation with Progressive Degradation
**Pattern**: Always return local tools/prompts/resources first; append remote tools if available; report per-remote health status.

**Implementation**:
```python
async def tools_list_aggregate(ctx):
    # Phase 1: local (always fast, always succeeds)
    local_tools = get_local_tools()
    results = {"local": local_tools, "remote": {}, "errors": {}}
    
    # Phase 2: remotes (fire-and-forget with per-remote timeout)
    for remote in settings.gateway.remotes:
        if not remote.enabled:
            results["remote"][remote.name] = {"tools": [], "status": "disabled"}
            continue
        try:
            remote_tools = await asyncio.wait_for(
                list_remote_tools(remote),
                timeout=10.0  # per-remote timeout
            )
            results["remote"][remote.name] = {"tools": remote_tools, "status": "healthy"}
        except asyncio.TimeoutError:
            results["errors"][remote.name] = "timeout"
            results["remote"][remote.name] = {"status": "timeout", "error_code": "TIMEOUT_10S"}
        except AuthError as e:
            results["errors"][remote.name] = str(e)
            results["remote"][remote.name] = {"status": "auth_failed", "error_code": "AUTH_ERROR"}
        except Exception as e:
            results["errors"][remote.name] = str(e)
            results["remote"][remote.name] = {"status": "failed", "error_code": "GENERIC_ERROR"}
    
    # Phase 3: aggregate and return
    return aggregate_tools(results)  # flatten local + available remotes, preserve status info
```

**Why It Works**:
- Local tools always available (no timeout risk)
- Remote failures logged but don't block response
- Caller sees which remotes are healthy/degraded
- Tools/prompts/resources/apps continue operating

---

### 2. Per-Remote Circuit Breaker with Exponential Backoff
**Pattern**: Isolate each remote's failures; after N failures, enter cooldown; stop sending traffic until recovery window.

**State Machine**:
```
CLOSED (normal)
  ↓ (1st auth error)
OPEN (cooldown, 5 min)
  ↓ (cooldown expires)
HALF_OPEN (probe recovery)
  ↓ (probe succeeds)
CLOSED (normal)
  ↓ (probe fails)
OPEN (cooldown, 10 min, doubled)
```

**Implementation**:
- Persist per-remote failure count and last-error timestamp
- When OPEN, return fast error (don't call remote)
- When HALF_OPEN, allow single probe; if succeeds, CLOSE; if fails, re-OPEN with doubled cooldown
- Expose via `/status` endpoint

---

### 3. Timeout-Safe Tool Calls with Async Isolation
**Pattern**: Remote tool calls inherit per-remote timeout (e.g., 30s), never block local execution.

**Implementation**:
```python
async def call_remote_tool(remote: str, tool_name: str, args: dict):
    # Check circuit breaker first (instant fail if OPEN)
    if is_remote_circuit_open(remote):
        raise RemoteCircuitOpen(f"{remote} in cooldown until {cooldown_until}")
    
    try:
        result = await asyncio.wait_for(
            direct.call_remote_tool_direct(remote, tool_name, args),
            timeout=30.0  # per-remote, configurable
        )
        clear_remote_error_count(remote)  # success → reset counter
        return result
    except asyncio.TimeoutError:
        increment_remote_error_count(remote)
        maybe_open_circuit(remote)
        raise ToolTimeout(f"{remote}/{tool_name} exceeded 30s timeout")
    except AuthError as e:
        increment_remote_error_count(remote)
        maybe_open_circuit(remote)
        raise ToolAuthError(str(e))
    except Exception as e:
        increment_remote_error_count(remote)
        maybe_open_circuit(remote)
        raise ToolError(str(e))
```

---

### 4. Degraded Mode Status Reporting
**Pattern**: Expose local health, per-remote health, and overall readiness via `/status` and `/ready`.

**Endpoints**:
- **`/health`**: Process up (fast)
- **`/ready`**: Local auth OK + at least one remote available OR local fallback sufficient (configurable)
- **`/status`**: Full JSON with local + per-remote state

```json
{
  "status": "degraded",
  "liveness": true,
  "local": {
    "tools_count": 10,
    "prompts_count": 3,
    "resources_count": 5,
    "apps_count": 1,
    "healthy": true
  },
  "gateway": {
    "mode": "hybrid",
    "route_policy": "local_preferred",
    "remotes": [
      {
        "name": "google-workspace-mcp",
        "enabled": true,
        "status": "open",
        "circuit_cooldown_until": "2026-08-17T15:45:00Z",
        "last_auth_error": "invalid_grant",
        "last_auth_error_at": "2026-08-17T15:40:00Z",
        "failure_count": 3,
        "last_successful_call": "2026-08-17T15:35:00Z"
      }
    ]
  },
  "readiness": {
    "local_sufficient": true,
    "comment": "local tools available; remotes degraded but not required"
  }
}
```

---

### 5. Graceful Degradation Mode Indicators
**Pattern**: Distinguish between:
- **Healthy**: Local + at least one remote working
- **Degraded**: Local working, all remotes down (but local fallback is sufficient)
- **Unhealthy**: Local tools/auth broken

**Operational Implications**:
- **Healthy** → Use preferred tools (local or remote)
- **Degraded** → Use local tools only; alert ops about remote failures; continue serving users
- **Unhealthy** → Block all MCP operations; page on-call

---

### 6. Observability + Debugging
**New Metrics**:
- Per-remote success rate, error rate, p99 latency
- Circuit breaker state transitions (CLOSED → OPEN → HALF_OPEN)
- Token refresh success/failure rates
- Local vs. remote tool call distribution

**Debug Endpoints**:
- `gateway_remote_auth_status(remote_name)` → auth state, last error, last refresh
- `gateway_diagnostic_info()` → full remote config (sanitized), circuit states, local tool inventory
- Logs: structured JSON with `remote=NAME`, `error_type=AUTH|TIMEOUT|NETWORK`, `circuit_state=CLOSED|OPEN|HALF_OPEN`

---

### 7. Recovery Automation
**Pattern**: When remotes degrade, enable automatic recovery paths:
1. Auth errors → `trigger_rebootstrap()` (clears cache, prepares for re-auth)
2. Timeout errors → backoff + jitter retry (handled by circuit breaker)
3. Operator action → `gateway_remote_manual_recovery(remote_name, action="reset_circuit" | "force_refresh" | "disable")`

---

### 8. Configuration for Resilience
**New `.env` Knobs**:
```bash
# Local-first behavior
ANTICAFARMACIA_GATEWAY_FALLBACK_LOCAL_ONLY_ON_REMOTE_ERROR=true  # if all remotes fail, use local only
ANTICAFARMACIA_GATEWAY_LOCAL_TOOL_PRIORITY_WEIGHT=100  # local tools listed first

# Per-remote timeout
ANTICAFARMACIA_GATEWAY_REMOTE_TOOL_LIST_TIMEOUT_MS=10000  # 10s
ANTICAFARMACIA_GATEWAY_REMOTE_TOOL_CALL_TIMEOUT_MS=30000  # 30s

# Circuit breaker
ANTICAFARMACIA_GATEWAY_CIRCUIT_FAILURE_THRESHOLD=3  # failures before OPEN
ANTICAFARMACIA_GATEWAY_CIRCUIT_COOLDOWN_BASE_MS=300000  # 5 min
ANTICAFARMACIA_GATEWAY_CIRCUIT_COOLDOWN_MAX_MS=1800000  # 30 min (exponential cap)

# Readiness policy
ANTICAFARMACIA_READY_REQUIRES_REMOTE_AVAILABLE=false  # local sufficient for readiness
```

---

## Cross-Cutting Design Principles

1. **Always return local first**: Local tools/prompts/resources are the baseline; remotes are additive.
2. **Fail open, not closed**: When a remote times out or errors, return local + status info, not "service unavailable".
3. **Per-remote isolation**: One broken remote cannot affect local or other remotes.
4. **Non-blocking aggregation**: Remote list/calls use `asyncio.wait_for(timeout)` to prevent blocking.
5. **Status visibility**: Every operation should be observable via `/status` or logs.
6. **Operator control**: Explicit admin tools to force recovery, reset circuit, disable remote without code change.
7. **Graceful degradation**: Service operates in degraded mode (local only) rather than failing hard.
