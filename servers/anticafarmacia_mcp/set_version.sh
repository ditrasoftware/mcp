#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <version>  (example: $0 1.0.5)" >&2
  exit 1
fi

NEW_VERSION="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/VERSION"

if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid version '$NEW_VERSION'. Expected semantic version like 1.0.5" >&2
  exit 1
fi

printf '%s\n' "$NEW_VERSION" > "$VERSION_FILE"

update_or_append_kv() {
  local file="$1"
  local key="$2"
  local value="$3"

  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

update_or_append_kv "$SCRIPT_DIR/.env_example" "ANTICAFARMACIA_MCP_VERSION" "$NEW_VERSION"
update_or_append_kv "$SCRIPT_DIR/.env_example" "ANTICAFARMACIA_MCP_IMAGE_REPO" "gcr.io/oxytrack-322814/ditra-anticafarmacia-mcp"
update_or_append_kv "$SCRIPT_DIR/.env_example" "ANTICAFARMACIA_MCP_IMAGE" "gcr.io/oxytrack-322814/ditra-anticafarmacia-mcp:${NEW_VERSION}"

echo "Version bumped to $NEW_VERSION"
echo "Updated:"
echo "- $VERSION_FILE"
echo "- $SCRIPT_DIR/.env_example"
