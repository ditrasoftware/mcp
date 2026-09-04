#!/usr/bin/env bash
set -euo pipefail
PROJECT_ID="oxytrack-322814"
IMAGE_NAME="ditra-playwright-mcp"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TAG="$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")"
IMAGE="gcr.io/$PROJECT_ID/$IMAGE_NAME:$TAG"
docker build --no-cache -f "$SCRIPT_DIR/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"
docker tag "$IMAGE_NAME" "$IMAGE"
docker push "$IMAGE"
echo "Pushed $IMAGE"
