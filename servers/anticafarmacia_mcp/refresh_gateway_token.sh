#!/usr/bin/env bash
set -euo pipefail

# Refresh GOOGLE_WORKSPACE_MCP_BEARER_TOKEN using refresh_token grant
# and recreate the anticafarmacia container.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="${ENV_FILE:-.env}"

if [[ -f "$ENV_FILE" ]]; then
  # Load .env without overriding non-empty values already provided by the host environment.
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"

    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

    if [[ -z "${!key+x}" || -z "${!key}" ]]; then
      export "$key=$value"
    fi
  done < "$ENV_FILE"
fi

TOKEN_ENDPOINT="${GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT:-https://workspace.dchat.ditra.app/token}"
AUTH_METHOD="${GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT_AUTH_METHOD:-none}"
CLIENT_ID="${GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_ID:-}"
CLIENT_SECRET="${GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_SECRET:-}"
REFRESH_TOKEN="${GOOGLE_WORKSPACE_MCP_OAUTH_REFRESH_TOKEN:-}"
SCOPE="${GOOGLE_WORKSPACE_MCP_OAUTH_SCOPE:-}"

if [[ -z "$REFRESH_TOKEN" ]]; then
  echo "ERROR: GOOGLE_WORKSPACE_MCP_OAUTH_REFRESH_TOKEN is empty." >&2
  exit 1
fi

if [[ "$AUTH_METHOD" == "client_secret_basic" || "$AUTH_METHOD" == "client_secret_post" ]]; then
  if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
    echo "ERROR: CLIENT_ID/CLIENT_SECRET required for auth method $AUTH_METHOD." >&2
    exit 1
  fi
fi

TMP_JSON="$(mktemp)"
trap 'rm -f "$TMP_JSON"' EXIT

curl_args=(
  -sS
  -X POST "$TOKEN_ENDPOINT"
  -H "content-type: application/x-www-form-urlencoded"
  --data-urlencode "grant_type=refresh_token"
  --data-urlencode "refresh_token=$REFRESH_TOKEN"
)

if [[ -n "$SCOPE" ]]; then
  curl_args+=(--data-urlencode "scope=$SCOPE")
fi

case "$AUTH_METHOD" in
  client_secret_basic)
    curl_args+=(-u "$CLIENT_ID:$CLIENT_SECRET")
    ;;
  client_secret_post)
    curl_args+=(--data-urlencode "client_id=$CLIENT_ID")
    curl_args+=(--data-urlencode "client_secret=$CLIENT_SECRET")
    ;;
  none)
    if [[ -n "$CLIENT_ID" ]]; then
      curl_args+=(--data-urlencode "client_id=$CLIENT_ID")
    fi
    ;;
  *)
    echo "ERROR: unsupported GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT_AUTH_METHOD=$AUTH_METHOD" >&2
    exit 1
    ;;
esac

curl "${curl_args[@]}" > "$TMP_JSON"

ACCESS_TOKEN=""
if command -v jq >/dev/null 2>&1; then
  ACCESS_TOKEN="$(jq -r '.access_token // empty' "$TMP_JSON")"
  ERROR_MSG="$(jq -r '.error_description // .error // empty' "$TMP_JSON")"
else
  ACCESS_TOKEN="$(python3 - <<'PY' "$TMP_JSON"
import json,sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    data=json.load(f)
print(data.get('access_token',''))
PY
)"
  ERROR_MSG="$(python3 - <<'PY' "$TMP_JSON"
import json,sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    data=json.load(f)
print(data.get('error_description') or data.get('error') or '')
PY
)"
fi

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "ERROR: token endpoint did not return access_token." >&2
  if [[ -n "$ERROR_MSG" ]]; then
    echo "DETAIL: $ERROR_MSG" >&2
  else
    echo "DETAIL: $(cat "$TMP_JSON")" >&2
  fi
  exit 1
fi

if [[ -f "$ENV_FILE" ]] && grep -q '^GOOGLE_WORKSPACE_MCP_BEARER_TOKEN=' "$ENV_FILE"; then
  sed -i "s|^GOOGLE_WORKSPACE_MCP_BEARER_TOKEN=.*|GOOGLE_WORKSPACE_MCP_BEARER_TOKEN=$ACCESS_TOKEN|" "$ENV_FILE"
else
  echo "GOOGLE_WORKSPACE_MCP_BEARER_TOKEN=$ACCESS_TOKEN" >> "$ENV_FILE"
fi

echo "Updated GOOGLE_WORKSPACE_MCP_BEARER_TOKEN in $ENV_FILE"

docker compose up -d --force-recreate

echo "Done. Container recreated with fresh bearer token."
