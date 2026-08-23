#!/bin/bash

set -euo pipefail

# Mirror anticafarmacia build workflow for deployment builds, but keep the key
# values overridable so CI and local releases can reuse the same script.
PROJECT_ID="${PROJECT_ID:-oxytrack-322814}"
IMAGE_NAME="${IMAGE_NAME:-ditra-devtest-mcp}"
TAG="${TAG:-1.0.0}"
FASTMCP_VERSION="${FASTMCP_VERSION:-4.0.0b2}"
PREFAB_UI_VERSION="${PREFAB_UI_VERSION:-0.19.1}"
NO_CACHE="${NO_CACHE:-true}"
PUSH_IMAGE="${PUSH_IMAGE:-true}"
TAG_NAME="gcr.io/$PROJECT_ID/$IMAGE_NAME:$TAG"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKERFILE_PATH="$REPO_ROOT/servers/ditra_devtest_mcp/Dockerfile"

build_args=()
if [[ "$FASTMCP_VERSION" != "" ]]; then
	build_args+=(--build-arg "FASTMCP_VERSION=$FASTMCP_VERSION")
fi
if [[ "$PREFAB_UI_VERSION" != "" ]]; then
	build_args+=(--build-arg "PREFAB_UI_VERSION=$PREFAB_UI_VERSION")
fi

build_flags=()
if [[ "$NO_CACHE" == "true" ]]; then
	build_flags+=(--no-cache)
fi

echo "Build Docker image $IMAGE_NAME ..."
docker build "${build_flags[@]}" "${build_args[@]}" -f "$DOCKERFILE_PATH" -t "$IMAGE_NAME" "$REPO_ROOT"

echo "Tag the Docker image $TAG_NAME ..."
docker tag "$IMAGE_NAME" "$TAG_NAME"

if [[ "$PUSH_IMAGE" == "true" ]]; then
	echo "Push the Docker image to GCR $TAG_NAME ..."
	docker push "$TAG_NAME"
fi

echo "Build complete."
