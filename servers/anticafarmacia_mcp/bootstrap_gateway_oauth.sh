#!/usr/bin/env bash
set -euo pipefail

# One-time OAuth Authorization Code + PKCE bootstrap helper.
# - Opens/prints authorization URL
# - Exchanges auth code for access_token + refresh_token
# - Persists tokens into .env for anticafarmacia gateway usage

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
RECREATE=1
if [[ "${1:-}" == "--no-recreate" ]]; then
  RECREATE=0
fi

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

AUTHORIZATION_ENDPOINT="${GOOGLE_WORKSPACE_MCP_OAUTH_AUTHORIZATION_ENDPOINT:-https://workspace.dchat.ditra.app/authorize}"
TOKEN_ENDPOINT="${GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT:-https://workspace.dchat.ditra.app/token}"
REGISTRATION_ENDPOINT="${GOOGLE_WORKSPACE_MCP_OAUTH_REGISTRATION_ENDPOINT:-https://workspace.dchat.ditra.app/register}"
AUTH_METHOD="${GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT_AUTH_METHOD:-none}"
CLIENT_ID="${GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_ID:-}"
CLIENT_SECRET="${GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_SECRET:-}"
REDIRECT_URI="${GOOGLE_WORKSPACE_MCP_OAUTH_REDIRECT_URI:-http://localhost:8787/callback}"
SCOPE="${GOOGLE_WORKSPACE_MCP_OAUTH_SCOPE:-openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile}"
AUTO_REGISTER="${GOOGLE_WORKSPACE_MCP_OAUTH_AUTO_REGISTER_CLIENT:-1}"
FORCE_REGISTER="${GOOGLE_WORKSPACE_MCP_OAUTH_FORCE_REGISTER_CLIENT:-0}"
REGISTERED_NOW=0
AUTO_LISTEN="${GOOGLE_WORKSPACE_MCP_OAUTH_AUTO_LISTEN_CALLBACK:-1}"

register_client() {
  local reg_payload reg_json
  reg_payload="$(python3 - <<'PY' "$REDIRECT_URI" "$AUTH_METHOD"
import json,sys
redirect_uri=sys.argv[1]
auth_method=sys.argv[2]
payload={
    "redirect_uris": [redirect_uri],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": auth_method,
    "client_name": "anticafarmacia-mcp-bootstrap",
}
print(json.dumps(payload))
PY
)"

  reg_json="$(curl -sS -X POST "$REGISTRATION_ENDPOINT" -H "content-type: application/json" --data "$reg_payload")"

  if command -v jq >/dev/null 2>&1; then
    CLIENT_ID="$(printf '%s' "$reg_json" | jq -r '.client_id // empty')"
    local maybe_secret
    maybe_secret="$(printf '%s' "$reg_json" | jq -r '.client_secret // empty')"
    if [[ -n "$maybe_secret" ]]; then
      CLIENT_SECRET="$maybe_secret"
    fi
  else
    CLIENT_ID="$(python3 - <<'PY' "$reg_json"
import json,sys
try:
    d=json.loads(sys.argv[1])
except Exception:
    d={}
print(d.get('client_id',''))
PY
)"
    local maybe_secret
    maybe_secret="$(python3 - <<'PY' "$reg_json"
import json,sys
try:
    d=json.loads(sys.argv[1])
except Exception:
    d={}
print(d.get('client_secret',''))
PY
)"
    if [[ -n "$maybe_secret" ]]; then
      CLIENT_SECRET="$maybe_secret"
    fi
  fi

  if [[ -z "$CLIENT_ID" ]]; then
    echo "ERROR: dynamic client registration failed; response: $reg_json" >&2
    exit 1
  fi

  REGISTERED_NOW=1
  echo "Registered OAuth client: $CLIENT_ID"
}

if [[ -z "$CLIENT_ID" ]]; then
  if [[ "$AUTO_REGISTER" == "1" || "$AUTO_REGISTER" == "true" || "$AUTO_REGISTER" == "yes" ]]; then
    register_client
  else
    echo "ERROR: GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_ID is empty." >&2
    exit 1
  fi
fi

# Some environments accidentally provide non-registered client IDs (e.g., email strings).
# If detected, replace with a dynamically registered client before opening the auth URL.
if [[ "$CLIENT_ID" == *"@"* ]]; then
  echo "Configured client_id looks like an email and is likely not registered: $CLIENT_ID"
  echo "Attempting dynamic client registration..."
  register_client
fi

if [[ "$REGISTERED_NOW" -eq 0 && ( "$FORCE_REGISTER" == "1" || "$FORCE_REGISTER" == "true" || "$FORCE_REGISTER" == "yes" ) ]]; then
  echo "GOOGLE_WORKSPACE_MCP_OAUTH_FORCE_REGISTER_CLIENT is enabled; registering a fresh client."
  register_client
fi

if [[ "$AUTH_METHOD" == "client_secret_basic" || "$AUTH_METHOD" == "client_secret_post" ]]; then
  if [[ -z "$CLIENT_SECRET" ]]; then
    echo "ERROR: GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_SECRET is required for auth method $AUTH_METHOD." >&2
    exit 1
  fi
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "ERROR: openssl is required to generate PKCE verifier/challenge." >&2
  exit 1
fi

urlencode() {
  python3 - <<'PY' "$1"
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
}

VERIFIER="$(openssl rand -base64 64 | tr -d '=+/' | cut -c1-96)"
CHALLENGE="$(printf '%s' "$VERIFIER" | openssl dgst -binary -sha256 | openssl base64 -A | tr '+/' '-_' | tr -d '=')"
STATE="$(openssl rand -hex 16)"

AUTH_URL="${AUTHORIZATION_ENDPOINT}?response_type=code&client_id=$(urlencode "$CLIENT_ID")&redirect_uri=$(urlencode "$REDIRECT_URI")&scope=$(urlencode "$SCOPE")&code_challenge=$(urlencode "$CHALLENGE")&code_challenge_method=S256&state=$(urlencode "$STATE")"

echo ""
echo "Open this URL in your browser and complete login/consent:"
echo "$AUTH_URL"
echo ""
AUTH_CODE=""

try_auto_callback_capture() {
  local py_output callback_host callback_port timeout_sec
  timeout_sec="${GOOGLE_WORKSPACE_MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS:-240}"

  py_output="$(python3 - <<'PY' "$REDIRECT_URI"
import sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
host = (u.hostname or "").strip().lower()
port = u.port
scheme = (u.scheme or "").strip().lower()
if not port:
    port = 443 if scheme == "https" else 80
print(host)
print(port)
PY
)"

  callback_host="$(printf '%s' "$py_output" | sed -n '1p')"
  callback_port="$(printf '%s' "$py_output" | sed -n '2p')"

  if [[ "$callback_host" != "localhost" && "$callback_host" != "127.0.0.1" ]]; then
    return 1
  fi

  if ! [[ "$callback_port" =~ ^[0-9]+$ ]]; then
    return 1
  fi

  local code_file err_file
  code_file="$(mktemp)"
  err_file="$(mktemp)"

  python3 - <<'PY' "$callback_port" "$code_file" "$err_file" "$STATE" "$timeout_sec" &
import socket
import sys
import time
from urllib.parse import urlparse, parse_qs

port = int(sys.argv[1])
code_file = sys.argv[2]
err_file = sys.argv[3]
expected_state = sys.argv[4]
timeout_sec = int(sys.argv[5])

body_ok = (
    "OAuth callback captured. You can return to the terminal.\n"
)
body_err = (
    "OAuth callback received but missing/invalid code. Return to terminal.\n"
)

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.settimeout(timeout_sec)
try:
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    conn, _ = srv.accept()
except Exception as e:
    with open(err_file, "w", encoding="utf-8") as f:
        f.write(str(e))
    sys.exit(0)

try:
    conn.settimeout(5)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    first = data.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
    parts = first.split(" ")
    path = parts[1] if len(parts) >= 2 else "/"
    q = parse_qs(urlparse(path).query)
    code = (q.get("code") or [""])[0]
    state = (q.get("state") or [""])[0]

    if code and (not expected_state or state == expected_state):
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)
        resp = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "Content-Length: " + str(len(body_ok)) + "\r\n"
            "Connection: close\r\n\r\n" + body_ok
        )
    else:
        with open(err_file, "w", encoding="utf-8") as f:
            if state and expected_state and state != expected_state:
                f.write("state mismatch")
            else:
                f.write("missing code")
        resp = (
            "HTTP/1.1 400 Bad Request\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "Content-Length: " + str(len(body_err)) + "\r\n"
            "Connection: close\r\n\r\n" + body_err
        )
    conn.sendall(resp.encode("utf-8"))
except Exception as e:
    with open(err_file, "w", encoding="utf-8") as f:
        f.write(str(e))
finally:
    try:
        conn.close()
    except Exception:
        pass
    srv.close()
PY
  local listener_pid=$!

  echo "Waiting for callback on $callback_host:$callback_port (timeout ${timeout_sec}s)..."
  wait "$listener_pid" || true

  if [[ -s "$code_file" ]]; then
    AUTH_CODE="$(cat "$code_file")"
    rm -f "$code_file" "$err_file"
    return 0
  fi

  if [[ -s "$err_file" ]]; then
    echo "Auto-callback capture did not complete: $(cat "$err_file")"
  fi
  rm -f "$code_file" "$err_file"
  return 1
}

if [[ "$AUTO_LISTEN" == "1" || "$AUTO_LISTEN" == "true" || "$AUTO_LISTEN" == "yes" ]]; then
  if try_auto_callback_capture; then
    echo "Received authorization code from local callback listener."
  fi
fi

if [[ -z "$AUTH_CODE" ]]; then
  echo "If browser lands on a localhost error page, copy the FULL URL from the address bar anyway."
  echo "Paste the full redirect URL or just the code value:"
  read -r AUTH_INPUT

  if [[ "$AUTH_INPUT" == *"code="* ]]; then
    AUTH_CODE="$(python3 - <<'PY' "$AUTH_INPUT"
import sys
from urllib.parse import urlparse, parse_qs
s=sys.argv[1]
try:
    q=parse_qs(urlparse(s).query)
    print((q.get('code') or [''])[0])
except Exception:
    print('')
PY
)"
  else
    AUTH_CODE="$AUTH_INPUT"
  fi
fi

if [[ -z "$AUTH_CODE" ]]; then
  echo "ERROR: could not parse authorization code." >&2
  exit 1
fi

TMP_JSON="$(mktemp)"
trap 'rm -f "$TMP_JSON"' EXIT

curl_args=(
  -sS
  -X POST "$TOKEN_ENDPOINT"
  -H "content-type: application/x-www-form-urlencoded"
  --data-urlencode "grant_type=authorization_code"
  --data-urlencode "code=$AUTH_CODE"
  --data-urlencode "redirect_uri=$REDIRECT_URI"
  --data-urlencode "code_verifier=$VERIFIER"
)

case "$AUTH_METHOD" in
  client_secret_basic)
    curl_args+=(-u "$CLIENT_ID:$CLIENT_SECRET")
    ;;
  client_secret_post)
    curl_args+=(--data-urlencode "client_id=$CLIENT_ID")
    curl_args+=(--data-urlencode "client_secret=$CLIENT_SECRET")
    ;;
  none)
    curl_args+=(--data-urlencode "client_id=$CLIENT_ID")
    ;;
  *)
    echo "ERROR: unsupported GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT_AUTH_METHOD=$AUTH_METHOD" >&2
    exit 1
    ;;
esac

curl "${curl_args[@]}" > "$TMP_JSON"

if command -v jq >/dev/null 2>&1; then
  ACCESS_TOKEN="$(jq -r '.access_token // empty' "$TMP_JSON")"
  REFRESH_TOKEN="$(jq -r '.refresh_token // empty' "$TMP_JSON")"
  ERROR_MSG="$(jq -r '.error_description // .error // empty' "$TMP_JSON")"
else
  PARSE_OUT="$(python3 - <<'PY' "$TMP_JSON"
import json,sys
path=sys.argv[1]
try:
    with open(path,'r',encoding='utf-8') as f:
        data=json.load(f)
except Exception:
    print('')
    print('')
    sys.exit(0)
print(data.get('access_token',''))
print(data.get('refresh_token',''))
PY
)"
  ACCESS_TOKEN="$(printf '%s' "$PARSE_OUT" | sed -n '1p')"
  REFRESH_TOKEN="$(printf '%s' "$PARSE_OUT" | sed -n '2p')"
  ERROR_MSG="$(python3 - <<'PY' "$TMP_JSON"
import json,sys
path=sys.argv[1]
try:
    with open(path,'r',encoding='utf-8') as f:
        data=json.load(f)
except Exception:
    print('')
    sys.exit(0)
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

upsert_env() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"

  if [[ -f "$ENV_FILE" ]]; then
    awk -v k="$key" -v v="$value" '
      BEGIN { done = 0 }
      $0 ~ "^" k "=" {
        print k "=" v
        done = 1
        next
      }
      { print }
      END {
        if (!done) print k "=" v
      }
    ' "$ENV_FILE" > "$tmp"
  else
    printf "%s=%s\n" "$key" "$value" > "$tmp"
  fi

  mv "$tmp" "$ENV_FILE"
}

upsert_env "GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT" "$TOKEN_ENDPOINT"
upsert_env "GOOGLE_WORKSPACE_MCP_OAUTH_TOKEN_ENDPOINT_AUTH_METHOD" "$AUTH_METHOD"
upsert_env "GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_ID" "$CLIENT_ID"
upsert_env "GOOGLE_WORKSPACE_MCP_OAUTH_CLIENT_SECRET" "$CLIENT_SECRET"
upsert_env "GOOGLE_WORKSPACE_MCP_OAUTH_REDIRECT_URI" "$REDIRECT_URI"
upsert_env "GOOGLE_WORKSPACE_MCP_OAUTH_SCOPE" "$SCOPE"
upsert_env "GOOGLE_WORKSPACE_MCP_BEARER_TOKEN" "$ACCESS_TOKEN"

if [[ -n "$REFRESH_TOKEN" ]]; then
  upsert_env "GOOGLE_WORKSPACE_MCP_OAUTH_REFRESH_TOKEN" "$REFRESH_TOKEN"
  echo "Stored access_token + refresh_token in $ENV_FILE"
else
  echo "Stored access_token in $ENV_FILE (no refresh_token returned by provider)"
fi

if [[ $RECREATE -eq 1 ]]; then
  docker compose up -d --force-recreate
  echo "Container recreated with new bearer token."
else
  echo "Skipped container recreate (--no-recreate)."
fi
