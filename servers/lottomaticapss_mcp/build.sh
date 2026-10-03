#!/bin/bash
set -e

# Build Lottomaticapss MCP Docker image from the repo root so the Dockerfile's
# `COPY servers/lottomaticapss_mcp/ ...` path resolves correctly.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION_FILE="$(cd "$(dirname "$0")" && pwd)/VERSION"
TAG="$(tr -d '[:space:]' < "$VERSION_FILE")"
if [[ $# -gt 0 && "$1" != "$TAG" ]]; then
  echo "Requested tag '$1' does not match VERSION '$TAG'. Run set_version.sh first." >&2
  exit 1
fi
docker build -f "$REPO_ROOT/servers/lottomaticapss_mcp/Dockerfile" \
  -t "gcr.io/oxytrack-322814/ditra-lottomaticapss-mcp:$TAG" \
  -t "lottomaticapss-mcp:latest" \
  "$REPO_ROOT"
