# Lottomatica PSS MCP

The canonical application version is stored in `VERSION`, exported as
`lottomaticapss_mcp.__version__`, and advertised in the MCP initialize response.
Use `./set_version.sh <major.minor.patch>` before a release; `build.sh` always
tags the image from that file.

The master business-context MCP for Lottomatica PSS connects enterprise workflows
to federated MCP servers, APIs, resources, prompts, MCP Apps, and other apps.
Ditra Analytics is the current analytics integration, not the full scope or
identity of the master gateway. Its infrastructure provides:

- **Infrastructure**: Authentication, settings, REST client, gateway capabilities
- **Middleware**: Tool hash rewriting, Prefab UI rendering, iOS tap fix injection
- **Gateway Support**: Hybrid local/remote tool routing with configurable policy
- **Extensibility**: Clear TODO sections for domain-specific tools, resources, prompts, and UI apps

## Ditra Analytics (Metabase) integration

This server includes a tool/resource/prompt set that connects to the Ditra
Analytics platform — the self-hosted Metabase Pro instance behind the
`lottomatica-dashboard-webapp` procurement portal (`https://analytics.ditra.io`,
dashboard `30` "Lottomatica PSS Dashboard", collection `6` "Lottomatica PSS
Analytics"). Local analytics convenience tools retain their existing unprefixed
names; federated analytics tools use the `ditra_analytics_` namespace.

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
- **Saved-card visualizations**: `visualize_card` is the native entry point. In
  delegated mode it prepares one native automatic-viewer widget using the connected
  account, with no automatic ECharts fallback. This does not preserve saved display
  settings or verify browser rendering. Outside connection mode it renders a card with its saved
  display and visualization settings through the `ui://lottomaticapss/saved-card.html`
  MCP App, which frames a short-lived signed static embed. It requires
  `METABASE_EMBEDDING_SECRET_KEY` and the card published for embedding (Sharing →
  Embed → Static/Guest embed → Publish). Unpublished cards return a message
  pointing to `visualize_card_query`, which uses the automatic chart viewer
  (saved pie/area/combo types are not preserved there).
  Guest embedding is unavailable for delegated account connections because it
  does not enforce that account's permissions. The native MCP automatic viewer
  preserves account permissions, not saved styles.
  Native saved-question embedding remains preferred when the actual widget
  origin and the user's independent analytics browser session are supported;
  an API bearer does not establish an iframe login. Existing password accounts
  do not need conversion to SSO. ECharts is an explicit alternative for saved area,
  pie, and combo charts, or an explicit renderer override. It queries through
  the selected connection, keeps that account's Metabase permissions, and caps
  chart data at 1,000 rows. It maps common dimensions, metrics, timeseries axes,
  area fill, and pie categories, but does not reproduce every Metabase style or
  dashboard placement override.
  Render once per requested result: `visualize_card` and `visualize_card_query` already prepare a
  widget, so following it with native `visualize_query` duplicates that output.
  Rendering metadata distinguishes preparation from verified browser rendering.
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

Fallback never follows HTTP 401/403 or ambiguous MCP application errors. Version
63 can return permission denials as HTTP-200 `isError` results without their
original status; those fail closed regardless of language. Explicit native
`Unknown tool: <requested name>` and JSON-RPC method-not-found errors still allow
fallback, as do transport failures and non-auth HTTP failures. A password-login
session may renew once after HTTP 401 using the same configured user, then retry
MCP; this does not switch to a REST operation or a different identity.

API-only mode, explicit API tools, pagination/model filters, parameterized queries,
dashboard-context queries, and saved-chart embedding remain available through
their existing paths. Each REST request must still be authorized by its own
configured identity. This policy prevents automatic denial bypass, not arbitrary
cross-tool escalation; per-caller authorization is still required at the gateway.

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

## Native rendering release candidate (1.1.42)

### Production source provenance (1.1.47)

- Running MCP-2 image: `gcr.io/oxytrack-322814/ditra-lottomaticapss-mcp:1.1.47`
- Image digest: `sha256:15c2dac2dfe5aea66bff12f1e3c4e4ca4fe23fead0c6e202980578797972956e`
- Source build-context archive SHA-256: `c360a87125437dfdc6e41e4c10bfac232785a9af93ac905bf7f0cb10f606d22c`
- The committed tree includes the exact application source and the native viewer's served assets, license notices, and Metabase patch from that hash-verified archive. Source maps and precompressed `.gz`/`.br` derivatives are omitted; the asset route serves the plain files referenced by the HTML and frontend chunks.
- The production image was built from a working-tree archive, not a Git commit. The release tag and commit identify the reconciled source snapshot; they do not change the image's original provenance labels.

Production patch 1.1.47 expands the saved-native contract to `scalar`, `pivot`,
and `row`, in both the gateway and frontend. The bundled SDK forwards its existing
optional `initialVisualization` setting for saved cards so sensibility checks do
not automatically replace their display. Scalar number settings and pivot row,
column, and totals settings are retained. Table output and ordinary-query defaults
are unchanged; pivot database/query constraints still apply and are not bypassed.

Validation: 127 gateway tests passed locally; image ran 127 with one Node skip,
remaining tests passed. Native/SDK/scalar/pivot run: 26 suites passed, 139 tests
passed and two skipped; full typecheck and production bundle build passed.
Production public bundle/health/auth checks and synthetic scalar/pivot payload
checks passed. Cards 882 and 707 require a real ChatGPT visual retest after
refreshing cached connector resources. No CSP, authorization, grant, or backend
analytics changes were made. Backup:
`/home/oxytrack_io/lottomaticapss_mcp/backups/1.1.47-predeploy-20261006T052241Z`.

Production patch 1.1.46 fills absent pie dimension/metric bindings only when saved
result metadata identifies exactly one breakout and one aggregation. Card 842's
confirmed roles resolve to `Classificazione ODA` and `sum`; saved formatting and
explicit selections are retained. Ambiguous columns are not guessed. Combo/area
and the native frontend bundle are unchanged. Local tests: 126 passed; container
ran 126 with one Node skip, remaining tests passed. Production contract checks
used the user-provided metadata fixture, not an actual query or browser render.
Retest `visualize_card(card_id=842)` once in ChatGPT to verify the displayed pie.
Backup: `/home/oxytrack_io/lottomaticapss_mcp/backups/1.1.46-predeploy-20261006T045911Z`.
Only image/version selectors changed; authentication, grants, policy, and viewer
flag were preserved.

Production update 1.1.45 enables the bundled saved native MCP viewer directly,
at the operator's request, without a staging service or replacement of analytics.
The gateway serves patched Metabase v0.63.18.1 frontend assets and supplies a
version-1 saved display/settings contract obtained under the selected account.
The analytics API and UI credential renewal continue to use that delegated account.
Dynamic assets load from the gateway; no guest credentials or SSO migration are used.
Supported saved displays are bar, line, area, pie, combo, and table; unsupported
types fail explicitly rather than silently claiming saved fidelity.

Validation: 123 gateway tests passed locally; container ran 123 with one Node
skip and the remaining tests passed. Native viewer/public-path tests: 18 suites,
55 tests passed; frontend typecheck and production bundle build passed. Public
bundle/health checks and synthetic saved-pie/resource/CSP checks passed. Actual
ChatGPT chart appearance and real-user visual/authorization acceptance remain
unverified. Refresh cached connector tool/resources before testing cards 842,
936, and 840 using `visualize_card` once per card.

The new `LOTTOMATICAPSS_NATIVE_SAVED_VIEWER_ENABLED` flag is enabled in the active
and GCIP profiles. Rollback backup:
`/home/oxytrack_io/lottomaticapss_mcp/backups/1.1.45-predeploy-20261006T044132Z`.
An earlier guarded attempt rolled back because of an unrelated Compose field;
the final rollout changed only image/version selectors and this viewer flag.
Authentication, grants, connection policies, ports, networks, and volume bindings
were preserved. Card 850's SQL/database relation was not changed.

Previous release 1.1.44 fixed modern list-shaped parameter template tags and
preserves downstream `construct_query` error results before query-handle lookup.
Local tests: 121 passed; Python 3.13 container: 121 ran, one Node-dependent skip,
remaining tests passed. Synthetic checks confirmed both fixes in the deployed
image; public health is 200 and anonymous MCP remains 401. Active/GCIP profiles
changed only image/version selectors; policies and credential mounts are unchanged.
Backup: `/home/oxytrack_io/lottomaticapss_mcp/backups/1.1.44-predeploy-20261006T034046Z`.
Card 850's missing PostgreSQL relation remains a separate owner-managed repair.

Gateway 1.1.43 adds `visualize_card(card_id, output=...)` modes:

- `native` remains the default, preserving existing ChatGPT behavior.
- `table` returns saved-question data for clients such as DitraChat that do not
  support MCP Apps. It queries under the selected connection, without UI
  credentials, guest tokens, or another renderer invocation.
- `auto` checks the negotiated `io.modelcontextprotocol/ui` extension and returns
  a table unless the client advertises support. It is opt-in because a working
  legacy UI client might not advertise that capability.

Tables expose at most 50 rows, 30 columns, and 160 characters per text/JSON cell,
with total row/column counts and a truncation flag. These are response bounds,
not limits on the downstream saved query's computation. Version 1.1.43 was
deployed to MCP-2. Local tests: 118 passed; Python 3.13 container: 118 ran, one
Node-dependent skip, remaining tests passed. Production schema/table routing was
checked with synthetic identity/data, without using a real user's downstream grant.
Only image/version selectors changed; policies, credentials, and volume bindings
were preserved. Backup:
`/home/oxytrack_io/lottomaticapss_mcp/backups/1.1.43-predeploy-20261006T002047Z`.

The isolated candidate image is
`gcr.io/oxytrack-322814/ditra-lottomaticapss-mcp:1.1.42-rc.1`; its application
version is `1.1.42`. It was built on MCP-2 from an uncommitted, secret-free
working-tree archive and was not pushed to the registry. The tested image was
tagged `1.1.42` and deployed at 2026-10-05 23:59 UTC. Production is healthy with
unchanged credential-volume bindings. Native automatic rendering is not faithful
saved-question rendering.

Validation on 2026-10-05:

- Local suite: 114 tests passed. A mock-upstream shutdown emitted
  `ClosedResourceError` and a secondary ASGI response error despite passing tests.
- Python 3.13 candidate: 114 tests ran, one Node-dependent test skipped, remaining
  tests passed; dependency check clean and no ASGI traceback in that run.
- An isolated real HTTP-entrypoint check returned health 200 and verified that
  synthetic ticket/code query values were redacted. No production environment
  files, OAuth credentials, volumes, or published ports were used.

For rollback-safe rollout, back up active/rollback profiles and preserve encrypted grants,
store keys, GCIP configuration, and volume bindings. Explicitly add
`visualize_card` to the existing Ditra connection's tool allowlist and retain
`ui://ditra_analytics/metabase/visualize-query.html` in its resource allowlist.
The previous production policy did not allow `visualize_card`; the rollout added
only that tool entry to the existing Ditra policy in the active and GCIP profiles.
Backups, including OAuth storage, are under
`/home/oxytrack_io/lottomaticapss_mcp/backups/1.1.42-predeploy-20261005T235920Z`.
Production checks confirmed native tool metadata and preparation using synthetic
identity/data, and live HTTP query redaction. They did not use a real user grant
or verify browser rendering. No embedding-origin or SSO settings were changed.
Refresh host tool catalogs after rollout; verify one native widget per call,
no automatic ECharts invocation, token refresh, and authorization denials in
both ChatGPT and DitraChat. Browser rendering remains a user acceptance gate.

### Authenticated saved-question proof of concept

Public `/question/936` headers on 2026-10-05 restrict `frame-ancestors` to
`http://localhost:5173`, `https://localhost:5173`, and `https://analytics.ditra.io`.
This currently blocks framing by ChatGPT and DitraChat. HTTP 200 serves the app
shell and does not prove authenticated access to the saved question.

1. Capture the actual widget origin and every ancestor origin in each host.
  Review exact origin additions before changing analytics embedding policy;
  do not allow all origins or disable CSP/CSRF.
2. Check full-app embedding support and browser cookie behavior on the deployed
  Metabase version. The documented SSO flow is not an approved account migration;
  preserve existing password accounts and do not enable SSO automatically.
3. In the same browser, sign into analytics directly using the intended account.
  Verify it matches the connected Ditra account before any iframe test. An
  independent browser session can belong to a different account; MCP OAuth
  does not establish or bind that session. A standalone iframe cannot assert
  that identity through cross-origin inspection.
4. Test the saved-question URL using that session under the actual host origins.
  Compare card 936's saved series styles, labels, and colors with analytics.
  Repeat signed out, with denied permissions, and with a different browser
  account. Stop if permissions or account binding cannot be guaranteed.
5. Check third-party-cookie restrictions on desktop and mobile. An iframe load
  event is not proof of a rendered chart. Require direct visual inspection.

Until these gates pass, do not expose authenticated saved-question framing as
the delegated renderer. Never use shared guest credentials or forward OAuth
bearers/session cookies into iframe URLs. If safe browser-session binding is
not possible, evaluate an upstream native MCP renderer enhancement to consume
saved display/settings under the existing delegated grant instead.

### Upstream native fidelity implementation boundary

Source inspection of Metabase tag `v0.63.18.1` identifies the missing contract:

- `frontend/src/metabase/embedding/mcp/hooks/useMcpApp.tsx` reads only `query` and
  `prompt` from the tool result.
- `frontend/src/metabase/embedding/mcp/McpUiAppRoute.utils.ts` constructs the
  deserialized card with `display: "table"` and fixed MCP visualization settings.
- `frontend/src/metabase/embedding/mcp/hooks/useMcpVisualizationSelector.ts`
  selects available displays from query results and captures the default display.

A faithful-native implementation requires a maintained upstream frontend change,
not an iframe-login or gateway tool-name change:

1. Extend the native tool-result contract with optional, validated saved display
  and visualization settings. Read them from card metadata under the same
  delegated account; do not trust a supplied card ID as proof of authorization.
2. Carry the optional metadata through `useMcpApp` and the UI route. Construct the
  SDK question with the saved display/settings and retain its saved display
  rather than allowing automatic selection to replace it. Preserve the current
  automatic behavior when no saved metadata is present.
3. Negotiate/version the extended contract before the gateway sends it. Do not
  insert visualization fields into MBQL or claim the current viewer honors
  fields it never reads. Keep UI credential renewal, query repair, drill-through,
  and existing per-connection identity isolation intact.
4. Test card 936's combo series, an area and pie question, and an ordinary query.
  Include refresh/query switching, expired credentials, inaccessible cards,
  cross-user isolation, and a non-MCP-Apps client. Compare saved styles visually
  in the actual ChatGPT widget before asserting fidelity.

An isolated upstream patch and validation record are preserved in
[the native renderer design](../../design/native-saved-card-renderer/design.md).
The supported upstream environment now passes 17 native viewer suites (50 tests),
full frontend typecheck, and the production frontend bundle build. The earlier
reduced-harness failures are superseded. An isolated analytics service, negotiated
gateway contract, real-user authorization checks, and visual staging validation
are still required; no claim of saved native fidelity is made yet.
No production Metabase files or embedding settings were modified. Existing password accounts, GCIP separation, and delegated
OAuth grants remain unchanged. DitraChat has no MCP Apps support; lack of a
widget/resource read there is expected rather than a rendering incident.

## Business skills and upstream compatibility

FastMCP's `SkillProvider` exposes the local, original business skill at
`skill://lottomatica-pss/SKILL.md` and its file/hash manifest at
`skill://lottomatica-pss/_manifest`. Both appear in resource discovery and the
local resource registry. `get_business_guidance` returns the same skill for
clients that expose tools but not resource reads or prompt retrieval. Server
instructions direct agents to read it before business workflows. Clients still
decide whether to follow that guidance; skills are not authorization enforcement.

The skill uses Lottomatica PSS and Ditra Analytics branding while preserving
native URIs, fields, schemas, and app metadata. It covers KPI definitions,
dashboard versus model semantics, query construction, visualization limits,
federation, and credential boundaries. The skill remains available offline even
when a downstream integration cannot connect.

Verified on 2026-10-04 against the latest published 63-series Git tag found,
`v0.63.19.1`: there are no native MCP skill packs in that release. Its native
Markdown resource is `metabase://docs/construct-query.md`, mounted here as
`metabase://ditra_analytics/docs/construct-query.md`. Native entity reads through
`read_resource` are a different contract from MCP protocol resource reads.
Newer development source contains MCP v2 `SKILL.md` packs served by `learn`;
do not advertise those tools or their syntax until the actual downstream
catalog supports them. The local skill is not a copied upstream skill.

Versioned evidence:
- https://github.com/metabase/metabase/blob/v0.63.19.1/src/metabase/mcp/resources.clj
- https://github.com/metabase/metabase/blob/v0.63.19.1/docs/ai/mcp.md
- https://github.com/metabase/metabase/blob/master/src/metabase/mcp/v2/skills.clj
- https://gofastmcp.com/servers/providers/skills

## Recommended authentication and authorization

For human clients, use the existing FastMCP `oidc_proxy` mode with the enterprise
identity provider. Configure the public gateway base URL, OIDC discovery URL,
client credentials, persistent signing/storage configuration, and approved client
redirect URIs. Validate token issuer, gateway audience, expiry, and required
scopes; bind tenant membership and permissions to verified identity, not a caller
header. Prefer verified ID tokens. Request refresh/offline access only where the
identity provider supports it. Initial login/consent is expected; valid refresh
credentials should avoid repeated prompts until expiry, revocation, or policy
requires reconnection.

For unattended workloads, use workload identity or an identity provider's
supported client-credentials flow with narrow gateway scopes. This requires an
appropriately configured verifier/authorization server; the existing OIDC proxy
mode is not evidence that machine grants are automatically supported. Do not use
human passwords or a shared browser account for agent authentication.

Authorize each operation before calling any integration. Use read, query, write,
and administrative policies, defaulting to read-only and enforcing at execution
as well as catalog filtering. Backend permissions remain an additional boundary.
Never forward a token intended for this gateway to an unrelated downstream API.

Choose downstream identity explicitly:
- Delegated user access: complete the integration's supported OAuth consent once
  per user and integration, then refresh silently. Key grants and retained MCP
  sessions by verified issuer, subject, tenant, integration, and granted scopes.
  Use token exchange/on-behalf-of only when the target supports it.
- Service access: provision least-privilege API keys, service principals, or
  workload credentials once per approved integration/tenant. Apply gateway data
  authorization before using them; they do not inherit the caller's permissions.
- Interactive analytics embedding: use per-viewer JWT SSO with the viewer's
  analytics permissions. Backend API authentication alone does not log the
  embedded browser in. Never expose a shared backend account to all viewers.

Store credentials in a managed secret store or encrypted durable grant store,
separate from model-visible results. Handle refresh rotation atomically and
serialize refreshes. Treat revoked grants as requiring reconnection. Do not
fallback from 401/403 or an authorization denial to a stronger service credential.
Audit both the initiating identity and downstream execution identity, without
logging secrets.

Current limitations: compose defaults to no inbound auth; the auth middleware
does not yet enforce capability scopes; the downstream credential store and
retained sessions are integration-scoped rather than user-scoped; MCP-to-REST
fallback for availability or unsupported features can select a separately
configured identity, but authentication/authorization denials cannot trigger it.
Enabling OIDC alone does
not fix these authorization boundaries. The skill integration does not enable
auth, migrate grants, or change production settings.

## GCIP master authentication and no-auth testing

`LOTTOMATICAPSS_MCP_AUTH_MODE=gcip` enables a tenant-bound login adapter around
FastMCP's OAuth proxy. FastMCP handles client registration, client PKCE, consent,
callback browser binding and audience-bound MCP token issuance. The adapter lets
the browser authenticate directly to GCIP using email/password or the configured
Google provider. It verifies signed GCIP ID tokens, project audience and tenant,
then applies the configured master-access policy before handing a short-lived
PKCE-bound code back to FastMCP. Master credentials are never forwarded to Ditra
Analytics.

The supplied project is `oxytrack-322814`, tenant `lottomatica-pss-tn7m6`.
The Google OAuth client ID is in `.env_example`; it is not the GCIP web API key.
Set these runtime values directly in private server configuration:
- `LOTTOMATICAPSS_GCIP_WEB_API_KEY`: the project's Firebase/GCIP web API key,
  restricted as appropriate for Identity Toolkit and Secure Token APIs. The key
  is browser-visible configuration, not a substitute for authorization.
- `LOTTOMATICAPSS_GCIP_AUTH_DOMAIN`: the configured Firebase auth hostname, with
  no scheme or path. Confirm its Google callback `/__/auth/handler` in the
  Google provider configuration and add the MCP hostname to authorized domains.
- `LOTTOMATICAPSS_GCIP_SIGNING_KEY`: separate stable high-entropy signing material,
  at least 32 characters, entered directly on the server, never in chat.
- Set `LOTTOMATICAPSS_GCIP_ACCESS_MODE` to exactly one of `subjects`, `claim`, or
  `tenant`:
  - `subjects` (default): use `LOTTOMATICAPSS_GCIP_ALLOWED_SUBJECTS` for an
    explicit UID allowlist.
  - `claim`: use `LOTTOMATICAPSS_GCIP_ACCESS_CLAIM` for a signed custom boolean
    claim such as `mcp_access=true`.
  - `tenant`: accept any valid ID token from the configured GCIP project and
    tenant. Use only when tenant enrollment is centrally controlled. This grants
    master-gateway login, not downstream integration access.
- Configure only the setting for the selected policy:
  - `LOTTOMATICAPSS_GCIP_ALLOWED_SUBJECTS`: explicitly approved GCIP user UIDs,
    comma- or whitespace-separated, for `subjects` mode. This is not an
    email/domain allowlist.
  - `LOTTOMATICAPSS_GCIP_ACCESS_CLAIM`: a signed custom boolean claim name,
    for example `mcp_access`, for `claim` mode. GCIP/Firebase administrators assign this claim
    through the Admin SDK; the gateway accepts only a verified ID token where
    the claim is exactly `true`. Claims arrive on the user's next sign-in or ID
    token refresh. This keeps user authorization in GCIP instead of duplicating
    UIDs in gateway profiles.

For example, a privileged deployment script using the Firebase Admin SDK can
set the claim without discarding other custom claims:

```js
const user = await getAuth().getUser(uid);
await getAuth().setCustomUserClaims(uid, {
  ...user.customClaims,
  mcp_access: true,
});
```

Run this only in a trusted admin environment. Claim changes reach the MCP on the
user's next sign-in or ID-token refresh. Assign the claim only to approved users;
the gateway validates the signed claim but does not manage GCIP user enrollment.

The gateway always validates the GCIP signature, project, issuer and tenant.
Downstream authorization remains connection-scoped in every mode: users need an
explicit connection assignment and their own delegated grant to access Ditra
Analytics. In `tenant` mode, unassigned users can authenticate to the MCP master
but receive no downstream tools/resources/prompts. A UID allowlist alone cannot
authenticate users when no identity provider is configured; use
`LOTTOMATICAPSS_MCP_AUTH_MODE=none` only for restricted testing.
- `LOTTOMATICAPSS_GCIP_CLIENT_REDIRECT_URIS`: approved ChatGPT/editor callbacks.
- `LOTTOMATICAPSS_MCP_BASE_URL`: `https://mcp.lottomatica-pss.ditra.app` (without
  `/mcp`) when switching the existing endpoint. The host must route OAuth and
  `/gcip/*` endpoints as well as `/mcp`. Internal token exchange calls the public
  HTTPS base URL; ensure it is reachable from the container.

GCIP mode requires explicit `LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON` (use `[]`
for an initial login-only pilot), encrypted downstream-store configuration and
the durable FastMCP OAuth volume. It never implicitly enables shared credentials.
The GCIP refresh grant is held in FastMCP encrypted storage, and the adapter
verifies renewed identity/tenant/UID before returning renewed tokens. Revocation
or renewal failure stops access; no automatic downgrade to no-auth is allowed.

To test the existing unauthenticated service explicitly:

```env
LOTTOMATICAPSS_MCP_AUTH_MODE=none
LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON=
```

GCIP settings may remain configured but unused in this mode. Keep no-auth testing
restricted to authorized environments: legacy service credentials can still
expose business data. Authenticated and no-auth access are mutually exclusive
at the same endpoint; changing mode requires restarting/recreating the service.
The existing live no-auth service is not switched by this implementation.

For a deployed service with private `.env.none` and `.env.gcip-pilot` profiles,
`set_auth_mode.sh none|gcip` applies the mode and its matching credential-store
settings, then recreates the container with rollback on failure. It retains the
current image and never prints profile values. Run it with the required Docker
and private-file permissions. Do not change only the auth flag: legacy no-auth
testing also needs its original grant-store path and encryption configuration.

The adapter is a single-worker pilot using documented FastMCP OAuth behavior
plus its pinned 4.0.11 transaction/storage interfaces; retest those interfaces
on framework upgrades. Live GCIP sign-in, Google popup behavior, deployed route
configuration and per-user downstream consent still need acceptance testing.
Do not describe this as production-ready or a completed downstream Connect UI.

## Opt-in integration connection separation

Connection separation is disabled by default. The deployed no-auth service is
not migrated or reconfigured by these local changes. With the option disabled,
existing service credentials, tools, prompts, and guest chart embeds continue
through their legacy paths.

Set `LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON` to a metadata-only JSON array to
enable separation. An explicit `[]` enables denial of all downstream connections;
an empty environment value leaves legacy mode active. Startup also requires a
master auth provider, a private `LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_STORE_PATH`,
and `LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_ENCRYPTION_KEY` (a Fernet key generated
and entered directly on the server). Use a new encrypted store path: the legacy
plaintext store is not silently imported or converted.

Example connection metadata, with no credentials:

```json
[
  {
    "id": "ditra-account-example",
    "remote": "ditra-analytics",
    "mode": "delegated",
    "tenant": "approved-business-tenant",
    "issuer": "https://approved-master-token-issuer",
    "subjects": ["verified-master-uid"],
    "credential_ref": "approved-ditra-account-grant",
    "downstream_account_id": "verified-analytics-user-id",
    "required_scopes": ["mcp:access"],
    "tools": ["search", "get_card", "run_card_query", "answer_dashboard_kpi", "visualize_card", "visualize_card_query", "visualize_card_echarts"],
    "resources": ["ditra-analytics://dashboard-summary", "ui://ditra_analytics/metabase/visualize-query.html", "ui://ditra_analytics/metabase/echarts-saved-card.html"],
    "prompts": []
  }
]
```

The verified master token supplies issuer, subject, scopes, and tenant. GCIP
tenant claims can be read from `firebase.tenant`; validated `tenant_id` and Entra
`tid` claims are also supported. Use the issuer of the verified master access
token, not an unverified login hint. An OAuth-facing GCIP login bridge must carry
the stable identity and tenant into that verified context; configuring GCIP's
email/password provider alone does not implement this bridge.

Delegated connections have exactly one owner. Service connections may explicitly
assign several subjects, but their credentials have the service identity's
permissions, not those of each assigned person. Wildcard owners and tool
allowlists are rejected. Optional required scopes are enforced in addition to
ownership. Tools, resource URIs, and federated prompts are explicitly allowed;
native tool names inside a federated namespace use their unprefixed names.
Configure one unambiguous connection per caller/integration for discovery.

Credentials are encrypted separately under `connection:<credential_ref>` in the
runtime store, never in the connection metadata or model-visible arguments. A
trusted administrator can provision a previously authorized OAuth grant using
`set_runtime_remote_credentials` within its `connection_scope`. Provisioning must
verify that the grant belongs to the intended downstream account; the optional
account ID is mapping metadata, not proof of account ownership. User-specific grants
use `TOKEN_ENDPOINT`, `CLIENT_ID`, `CLIENT_SECRET` where required, `REFRESH_TOKEN`,
and approved `SCOPE`. A service connection may use `API_KEY`. No GCIP password is
reused and no downstream account is converted to SSO.

`list_integration_connections` returns only assigned connection IDs, integrations,
modes, and `Configured`, `Connection Required`, or `Reconnect Required` states.
Configured means credentials exist, not that downstream authorization was tested.
Administrative generic gateway tools are blocked in this mode; remote tool
dispatch still checks the actual integration and target tool. Authorization audit
events record caller identity, connection and decision without credentials.

The selected connection controls both native MCP and REST augmentation headers.
There is no fallback to global API keys, passwords, bearer tokens, or legacy
grant records. REST endpoints must accept that connection's credentials and
permissions; a scoped MCP grant is not assumed to authorize every REST endpoint.
Missing support is an explicit failure, not a service-account substitution.
Shared guest-embedding secrets are unavailable in separated mode because they
do not enforce the selected account's downstream permissions. Use the selected user's native
MCP viewer or a separately designed per-viewer embedding integration. Resource
templates are not advertised in the first separation implementation; authorize
explicit URIs instead.

Token renewals use connection-scoped locks, expiry margin/jitter and a rejected-
token check so concurrent stale requests reuse the newly issued token. Terminal
refresh errors stop until reconnection clears the failure state; transient HTTP
and network refresh failures have a short cooldown. Direct and mounted clients
share per-request auth and never retry a 403 by forcing token refresh. Credential
rotation is encrypted and atomically written. Failure cooldowns are process-local;
a restart may attempt a revoked grant once again before blocking it.
Refresh and Ditra account callback writes share async coordination. Async file-lock
acquisition is non-blocking, and account pinning is rechecked inside the write
lock. Tokens with unknown expiry are not cached as if they lasted one hour.
OAuth callbacks validate a returned issuer exactly and require it when advertised;
failed issued grants are revoked best-effort when a trusted revocation endpoint
is advertised. Failed revocation is not a guarantee that a remote grant is gone.

Retained MCP clients and analytics metadata/permission caches are partitioned by
verified identity, connection and available MCP session ID. For stateless clients
without a conversation/session identifier, isolation is per identity/connection,
not guaranteed per conversation. Single-worker deployment is the supported first
stage: do not run multiple processes against the file store as a distributed
grant manager. For stateless HTTP, the fallback includes the verified OAuth
client ID, not a newly generated per-request session ID. Local native visualization,
mounted tools and UI credential refresh share the retained downstream session.
Metabase 63 uses legacy MCP negotiation for its session-bound handles. The pool
holds at most 128 clients, expires clients after 15 idle minutes, and checks idle
expiry every minute. Active operations are not evicted; a full pool rejects new
sessions rather than disrupting active ones. Shutdown closes retained clients.
Expired query handles must be reconstructed. A shared transactional encrypted
store and distributed single-flight remain required before horizontal scale.

GCIP provides the master OAuth login bridge, and Ditra Analytics account
Connect/consent callbacks are described below. Background job delegation is not
implemented by this connection layer. Existing shared admin callbacks are disabled
in separated mode rather than enrolling a global grant. A restricted authenticated
pilot must verify two users, per-account MCP/REST support, grant ownership,
renewal and revocation before broader deployment.

## Ditra Analytics account setup

For GCIP-authenticated users with an assigned or self-service delegated account
connection, `connect_integration` returns a five-minute browser link. Open it in
the same browser as the master login. The gateway re-verifies that browser's master
identity, consumes the ticket, and starts a separate Ditra Analytics OAuth authorization
code flow with PKCE, state, and an HttpOnly browser-binding cookie. GCIP credentials
are not forwarded and the Ditra Analytics account is not converted to SSO.

With GCIP tenant access mode, set `LOTTOMATICAPSS_GATEWAY_DITRA_SELF_SERVICE=true`
to let a tenant user who has no explicit Ditra assignment request their own
account connection. The gateway requires exactly one administrator-configured
delegated Ditra policy template in `LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON`.
It derives a stable, unique connection ID and encrypted credential reference from
the verified issuer, tenant, and subject, and copies only the template's tool,
resource, and scope allowlists. It does not copy the template owner's grant or
downstream account ID. OAuth consent then pins that user's own analytics account.
Set the flag to `false` to require administrators to assign each connection
explicitly. This flag has no effect outside GCIP tenant mode.

The connection requests `mb:full` explicitly, plus native read/query/MCP UI scopes.
The running Metabase v1.63.18.1 advertises this scope. A token with only `agent:*`
scopes cannot call ordinary `/api/dashboard` or `/api/card` endpoints; a token
with `mb:full` can use the general API as its authenticated user. This is broader
than a read-only scope, not an administrator bypass. Keep gateway tool allowlists
restricted and prefer a downstream account with only necessary permissions.

The registration and authorization requests must both include these scopes.
The callback checks `/api/user/current` and Dashboard 30 under the newly issued
bearer before persisting a renewable grant. It records the verified account ID,
and stores the grant encrypted under the user-specific credential reference.
By default, an existing account-ID pin prevents a different Ditra account from
replacing the grant. To deliberately switch, call
`connect_integration(account_email="user@example.com")`; this issues a fresh
consent link with that email as a login hint. The callback verifies the actual
`/api/user/current` email and only replaces the grant on a match. If another
account is already signed into Ditra Analytics in that browser, sign out of
Ditra Analytics there and retry. A mismatched login leaves the existing grant
unchanged. Administrator-pinned account IDs cannot be switched this way.
Existing narrow grants require fresh consent; refresh cannot silently add scopes.
No global API key or service account is used to bypass a denied user grant.

After completion, refresh tool discovery and call `list_dashboard_cards` for
Dashboard 30. If the master browser identity cookie is absent or expired,
reconnect master authentication first. The master-login adapter now creates that
cookie; users logged in before this change need one master reconnection.
The UI does not ask the model to collect passwords or OAuth token values.

## Ditra-only Microsoft SSO pilot

The separate `docker-compose-ditra-pilot.yml` uses Ditra tenant
`09150482-f0ba-4f90-b762-a639c1cb7a40`, not Lottomatica's tenant. It starts a
different container, binds its host port to loopback (8098 by default), and uses
a separate OAuth volume. It does not load the production `.env`, customer API
credentials, or downstream OAuth grants. Analytics is intentionally disconnected
until the login test is complete. This pilot is not yet provisioned or deployed.

### Entra registration

1. In the Ditra tenant, open Entra ID > App registrations > New registration.
   Use a separate name such as `Ditra MCP SSO Pilot` and select accounts in this
   organizational directory only (single tenant).
2. Add a **Web** redirect URI equal to the approved pilot HTTPS base URL plus
   `/auth/callback`. For a base URL without a path, the MCP endpoint is `/mcp`.
   Do not reuse the existing portal's client ID or select a public-client flow.
3. Under Enterprise applications, open this application and set **Assignment
   required? = Yes**. Assign only `waltercurti@ditra.io` for the pilot. If the
   tenant's licensing or policy prevents assignment enforcement, stop and add a
   gateway-side verified-identity allowlist before exposing the pilot.
4. Record the Application (client) ID, which is a GUID, not the sign-in email.
   Create a client secret and enter its **value**, not its secret ID, directly
   into the private server configuration. Never put it in chat or source control.
5. Request only `openid profile email offline_access` for this login pilot.
   Obtain administrator consent if Ditra policy requires it. No analytics or
   Microsoft Graph business-data permissions are needed for the SSO test.

### Server configuration

Use the keys from `ditra-pilot.env.example` in a private mode-600
`.env.ditra-pilot` outside the tracked source. Set:
- `DITRA_PILOT_BASE_URL`: the approved public HTTPS base URL, with no trailing slash.
- `DITRA_PILOT_CLIENT_ID`: the new Entra Application (client) ID.
- `DITRA_PILOT_CLIENT_SECRET`: the secret value, entered directly on the server.
- `DITRA_PILOT_SIGNING_KEY`: separate high-entropy key material kept stable across
  restarts; do not reuse production secrets.
- `DITRA_PILOT_CLIENT_REDIRECT_URIS`: the chosen MCP client's approved callback
  URLs, comma- or whitespace-separated. These are distinct from Entra's fixed
  `/auth/callback` URI. Do not use a broad wildcard merely to avoid configuration.
- `DITRA_PILOT_HOST_PORT`: an unused loopback port (default 8098).

Set DNS/TLS and a reverse proxy for the pilot hostname to that loopback port.
Forward `/mcp`, `/auth/callback`, the OAuth operational routes, and
`/.well-known/` discovery routes without rewriting their public base path.
Restrict management routes; `/health` is only a liveness check, not proof that
authentication works. Do not change the production hostname or its routing.

From the repository root, after all values and assignment controls are ready:

```bash
docker compose --project-name ditra-sso-pilot \
  --env-file /path/to/private/.env.ditra-pilot \
  -f servers/lottomaticapss_mcp/docker-compose-ditra-pilot.yml config --quiet
docker compose --project-name ditra-sso-pilot \
  --env-file /path/to/private/.env.ditra-pilot \
  -f servers/lottomaticapss_mcp/docker-compose-ditra-pilot.yml up -d --build
```

### Acceptance checks

- Anonymous MCP requests receive an authentication challenge, not the tool catalog.
- Your assigned Ditra account completes login and the MCP-client consent flow.
- A different unassigned Ditra account and an account from another tenant cannot
  access the pilot.
- Discovery advertises the pilot URL; ID-token verification uses the Ditra issuer
  and the new client ID. The pilot does not forward MCP's `resource` parameter
  to Entra and retains FastMCP's default consent/browser-binding protections.
- Refresh and restart retain valid authorization using the isolated OAuth volume;
  a revoked grant requires reconnection rather than another credential identity.
- Skills and business guidance work, but analytics calls cannot access customer
  data while the pilot has no downstream credentials.

Only after these checks, link the verified Ditra identity to the existing
analytics user ID and authorize an isolated downstream connection. Do not copy
the production OAuth grant store or enable shared-account browser sessions.

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
