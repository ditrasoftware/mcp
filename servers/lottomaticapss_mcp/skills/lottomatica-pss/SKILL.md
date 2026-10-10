---
name: lottomatica-pss
description: "Use when answering Lottomatica PSS procurement questions, reconciling dashboard KPIs, visualizing Ditra Analytics results, or choosing federated business capabilities."
---

# Lottomatica PSS Business Context

Lottomatica PSS MCP is the master business-context gateway. Ditra Analytics is
its analytics integration, not the identity or full scope of the gateway.
Additional integrations may provide MCP tools, API operations, resources,
prompts, MCP Apps, or other apps. Discover their current capabilities before use.
Present analytics features as Ditra Analytics. Preserve technical identifiers,
native resource URIs, query fields, tool arguments, and app metadata unchanged.

## Select the business workflow

- For a saved dashboard KPI, use `answer_dashboard_kpi` first. Supply the KPI
  name, an explicit period, and PSS/Niuma or a card ID when ambiguous. Preserve
  its saved filters, distinct-count key, and dashboard date mapping. Never
  substitute a broader model count for a dashboard KPI.
- For ad hoc supplier spending, use `answer_kpi`. Return the metric, resolved
  supplier, period, source, and applied filters. This model result is not
  automatically equivalent to a saved dashboard KPI.
- Before comparing totals, check period, population, counting grain, filters,
  and date field. Header-level and order-level filters may produce different
  totals. Do not describe unlike definitions as directly comparable.
- A requested KPI breakdown must retain the same qualifying population and
  counting definition. If no supported operation can do this, state the gap;
  do not silently replace it with an unfiltered model breakdown.
- Do not infer official process stages from populated fields without labeling
  them as inferred. Check duplicate amounts and counting grain before summing.

## Discover and query Ditra Analytics

The configured default dashboard is normally 30 and collection is normally 6.
Read `ditra-analytics://config` to confirm defaults rather than assuming them.
Use `list_dashboard_cards` for compact placements and `get_dashboard(full=true)`
only when full definitions or parameter mappings are necessary. Distinguish
card IDs from dashboard placement IDs and text headings from executable cards.

Use `search` for discovery; use explicit API tools when pagination or parameter
bindings require them. Inspect definitions and field metadata before querying.
Use `build_mbql_query` and `validate_mbql_query` rather than guessing query
syntax. Check `can_run_native_query` before attempting SQL. Return failures,
ambiguities, and partial results honestly; never manufacture missing rows.
Follow continuation tokens and identify any row or page limits.

The version-63 native query reference is available through the mounted resource
`metabase://ditra_analytics/docs/construct-query.md`. Read it before non-trivial
native query construction. This is a protocol resource; the separate
`ditra_analytics_read_resource` tool reads entities using its documented native
URI patterns. Those patterns are not automatically registered resource templates.

Version 63 has no native MCP skill-pack or `learn` contract in the verified
63.19.1 source. Do not call newer-version tools unless live discovery lists
them. This skill is local business guidance, not an upstream skill export.

## Visualizations and apps

- `visualize_card` accepts `output="table"` for hosts without MCP Apps support,
  including DitraChat. It returns bounded saved-question data, not a chart.
  `output="auto"` uses negotiated MCP Apps capability; the default remains
  `output="native"` for compatibility. Do not claim a non-app host displayed a widget.
- `visualize_card` is the default native entry point for a saved card. In delegated
  mode it prepares one native automatic-viewer widget under the selected account's
  permissions, without an automatic ECharts fallback. Saved display settings are
  not preserved by that viewer. Outside connection mode, configured published
  guest embeds retain saved settings. Shared guest credentials remain unavailable
  in delegated mode. Dashboard browser filters and placement overrides are not applied.
- Prefer native rendering. Authenticated saved-question embedding requires an
  allowed widget origin and the selected user's independent analytics browser
  session. API OAuth does not establish that iframe session. Existing password
  accounts remain valid; converting them to SSO is not a requirement.
- `visualize_card_query` is the native automatic viewer and remains the default
  for bar, line, and table questions. It chooses chart type from the result and
  does not apply the saved question's display settings.
- Only when the user explicitly requests ECharts, use `visualize_card_echarts`.
  For saved area, pie or combo fidelity, explain the native limitation before
  suggesting this alternative; do not silently switch renderers. It runs the saved card through the
  current Ditra Analytics connection, preserving account permissions, and maps
  supported dimensions, metrics, timeseries axes, area fill, and pie categories.
  It caps displayed rows at 1,000. It does not reproduce dashboard placement
  overrides or every backend-specific style setting.
- A call to `visualize_card_echarts` creates exactly one chart widget. Do not
  repeat it or call another visualization tool for the same card unless the user
  explicitly requests a comparison or refresh.
- A successful `visualize_card` or `visualize_card_query` call already prepares one chart widget.
  Do not call native `visualize_query` for that same result again. A deliberate
  refresh or a different rendering request is a separate operation.
- ECharts is an explicit override, not an automatic fallback. Both `visualize_card_echarts` and
  `ui://ditra_analytics/metabase/echarts-saved-card.html` must be explicitly
  allowed in the caller's connection policy.
- Native version-63 inline charts support bar, line, and table views. They are
  not the full analytics editor and do not accept an arbitrary chart-type spec.
- A successful tool call confirms preparation, not browser rendering. Do not
  claim visual verification without a renderer acknowledgment or inspection.
  The local rendering metadata reports native automatic rendering and the loss
  of saved settings; it does not claim full saved-question fidelity.
- Follow the listed app tool and resource metadata for drill-through. Query
  and drill-through handles can be bound to a downstream session and identity.
- Do not expose signed URLs, bearer tokens, or UI credentials in narrative
  answers. Do not regenerate results after a visualization unless requested.

## Federation and security boundaries

If the user's Ditra Analytics account connection needs setup, call
`list_integration_connections` and present its `setup_url` to the user. That
short-lived link starts OAuth consent for the user's Ditra Analytics account
in the same browser as the master login.
Alternatively call `connect_integration` if available in the client catalog.
When tenant self-service is enabled, users can authorize their own Ditra Analytics
account through OAuth; grants and permissions remain isolated per user.
If a different Ditra account should be connected to the current GCIP user, ask
which account email to use, then call `connect_integration` with that
`account_email`. The callback verifies the authenticated Ditra email before
replacing the current grant; if the browser session belongs to another account,
ask the user to sign out of Ditra Analytics and retry.
Service connections and missing connection assignments still require an administrator.

Use the actual tool catalog for available operations. `registry_summary` groups
local registrations but currently does not enumerate every bridge or diagnostic.
Prefer business tools over generic remote-call diagnostics. Preserve backend
provenance and distinguish MCP results from API augmentations.

Authorization is enforced by the gateway and integration, not by this skill.
Do not treat a user-provided email, tenant header, or model-generated argument
as verified identity. Never pass an inbound gateway token to an unrelated
downstream API. Do not fall back from a denied user operation to a stronger
service account. Missing consent or revoked authorization requires reconnection,
not an access workaround. Obtain confirmation for requested writes and never
change saved questions, dashboards, or permissions merely to answer a read query.