#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="oxytrack-322814"
ZONE="europe-west12-a"
INSTANCE="mcp-1"
REMOTE_DIR="/home/oxytrack_io/anticafarmacia_mcp"
REMOTE_NAME="google-workspace-mcp"

MODE="${1:-status}"
TOKEN="${2:-}"

run_remote() {
  local cmd="$1"
  gcloud --quiet compute ssh "$INSTANCE" --project "$PROJECT_ID" --zone "$ZONE" --command "$cmd"
}

print_status() {
  echo "1. Container + image status"
  run_remote "sudo docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep anticafarmacia-mcp"

  echo
  echo "2. Readiness"
  run_remote "sudo bash -lc 'PORT=8094; if [ -f \"$REMOTE_DIR/.env\" ]; then P=\$(grep -E \"^ANTICAFARMACIA_MCP_HOST_PORT=\" \"$REMOTE_DIR/.env\" | tail -n1 | cut -d= -f2); if [ -n \"\$P\" ]; then PORT=\$P; fi; fi; echo using_port=\$PORT; curl -sS http://127.0.0.1:\$PORT/ready'"

  echo
  echo "3. Runtime auth status (${REMOTE_NAME})"
  run_remote "sudo docker exec anticafarmacia-mcp python -c \"from anticafarmacia_mcp.settings import get_settings; from anticafarmacia_mcp.gateway.remote_auth import get_remote_auth_runtime_status; s=get_settings(); r=[x for x in s.gateway.remotes if x.name=='$REMOTE_NAME'][0]; print(get_remote_auth_runtime_status(r))\""
}

set_runtime_access_token() {
  if [ -z "$TOKEN" ]; then
    echo "Usage: $0 set-token <short-lived-access-token>" >&2
    exit 1
  fi
  echo "Setting runtime ACCESS_TOKEN for ${REMOTE_NAME}"
  run_remote "sudo docker exec anticafarmacia-mcp python -c \"from anticafarmacia_mcp.settings import get_settings; from anticafarmacia_mcp.gateway.remote_auth import _set_runtime_remote_secret; s=get_settings(); r=[x for x in s.gateway.remotes if x.name=='$REMOTE_NAME'][0]; _set_runtime_remote_secret(r, 'ACCESS_TOKEN', '$TOKEN'); print('runtime token set')\""
  echo
  print_status
}

clear_runtime_secrets() {
  echo "Clearing runtime secrets for ${REMOTE_NAME}"
  run_remote "sudo docker exec anticafarmacia-mcp python -c \"from anticafarmacia_mcp.settings import get_settings; from anticafarmacia_mcp.gateway.remote_auth import clear_remote_runtime_auth_secrets; s=get_settings(); r=[x for x in s.gateway.remotes if x.name=='$REMOTE_NAME'][0]; clear_remote_runtime_auth_secrets(r); print('runtime secrets cleared')\""
  echo
  print_status
}

authorize_smoke_test() {
  local redirect_uri="https://dchat.ditra.app/oauth/callback"
  local client_id="autoreg-smoke-$(date +%s)"
  local authorize_url="http://127.0.0.1:8094/authorize?response_type=code&client_id=${client_id}&redirect_uri=https%3A%2F%2Fdchat.ditra.app%2Foauth%2Fcallback&state=smoke&code_challenge=abc&code_challenge_method=S256"

  echo "Running authorize auto-register smoke test"
  echo "client_id=${client_id}"
  echo "redirect_uri=${redirect_uri}"

  run_remote "sudo bash -lc 'curl -sS -o /tmp/authorize_smoke_body -D /tmp/authorize_smoke_headers \"${authorize_url}\"; head -n 1 /tmp/authorize_smoke_headers; grep -i \"^location:\" /tmp/authorize_smoke_headers || true; head -c 220 /tmp/authorize_smoke_body; echo'"

  echo
  echo "Recent auth logs"
  run_remote "sudo docker logs --tail 80 anticafarmacia-mcp | grep -Ei 'auto-register|Unregistered client_id|/authorize' || true"
}

case "$MODE" in
  status)
    print_status
    ;;
  set-token)
    set_runtime_access_token
    ;;
  clear-token)
    clear_runtime_secrets
    ;;
  authorize-smoke)
    authorize_smoke_test
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    echo "Modes: status | set-token <token> | clear-token | authorize-smoke" >&2
    exit 1
    ;;
esac
