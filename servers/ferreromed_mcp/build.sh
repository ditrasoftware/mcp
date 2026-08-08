#!/bin/bash

set -euo pipefail

# Mirror ferreromed/api/app/build.sh style for deployment builds
PROJECT_ID="oxytrack-322814"
IMAGE_NAME="ditra-ferreromed-mcp"
TAG="1.5.1"
TAG_NAME="gcr.io/$PROJECT_ID/$IMAGE_NAME:$TAG"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Build Docker image $IMAGE_NAME ..."
docker build --no-cache -f "$REPO_ROOT/ferreromed_mcp/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"

echo "Tag the Docker image $TAG_NAME ..."
docker tag "$IMAGE_NAME" "$TAG_NAME"

echo "Push the Docker image to GCR $TAG_NAME ..."
docker push "$TAG_NAME"

echo "Build complete."
