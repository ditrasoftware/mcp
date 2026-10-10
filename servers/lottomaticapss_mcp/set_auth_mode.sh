#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ( "$1" != none && "$1" != gcip ) ]]; then
  echo "Usage: $0 none|gcip" >&2
  exit 1
fi

DEPLOY_DIR="${LOTTOMATICAPSS_DEPLOY_DIR:-$(cd "$(dirname "$0")" && pwd)}"
MODE="$1"
PROFILE="$DEPLOY_DIR/.env.$MODE"
if [[ "$MODE" == gcip ]]; then
  PROFILE="$DEPLOY_DIR/.env.gcip-pilot"
fi
test -f "$PROFILE"
BACKUP="$DEPLOY_DIR/.env.before-auth-switch-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$DEPLOY_DIR/.env" "$BACKUP"
chmod 600 "$BACKUP"
IMAGE=$(docker inspect --format '{{.Config.Image}}' lottomaticapss-mcp)

rollback() {
  local status=$?
  trap - ERR
  cp -p "$BACKUP" "$DEPLOY_DIR/.env"
  docker compose --project-directory "$DEPLOY_DIR" -f "$DEPLOY_DIR/docker-compose.yml" up -d --no-build --pull never --wait --wait-timeout 120
  exit "$status"
}
trap rollback ERR

docker run --rm -i --network none --entrypoint python -e REQUESTED_AUTH_MODE="$MODE" \
  -v "$DEPLOY_DIR:/runtime" "$IMAGE" - <<'PY'
import os
from dotenv import dotenv_values, set_key

mode = os.environ["REQUESTED_AUTH_MODE"]
profile = dotenv_values("/runtime/.env.gcip-pilot" if mode == "gcip" else "/runtime/.env.none")
keys = ["LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON", "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_STORE_PATH",
  "LOTTOMATICAPSS_GATEWAY_REMOTE_AUTH_ENCRYPTION_KEY", "LOTTOMATICAPSS_GATEWAY_DITRA_SELF_SERVICE"]
if mode == "gcip":
    keys += [key for key in profile if key.startswith("LOTTOMATICAPSS_GCIP_")]
    keys += ["LOTTOMATICAPSS_MCP_BASE_URL"]
for key in keys:
    set_key("/runtime/.env", key, profile.get(key) or "")
set_key("/runtime/.env", "LOTTOMATICAPSS_MCP_AUTH_MODE", mode)
os.chmod("/runtime/.env", 0o600)
print("Auth mode and matching credential-store profile applied; values withheld.")
PY
docker compose --project-directory "$DEPLOY_DIR" -f "$DEPLOY_DIR/docker-compose.yml" config --quiet
docker compose --project-directory "$DEPLOY_DIR" -f "$DEPLOY_DIR/docker-compose.yml" up -d --no-build --pull never --wait --wait-timeout 120
test "$(docker exec lottomaticapss-mcp printenv LOTTOMATICAPSS_MCP_AUTH_MODE)" = "$MODE"
echo "Auth mode active: $MODE. Previous configuration: $BACKUP"
trap - ERR