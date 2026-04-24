#!/usr/bin/env bash
set -euo pipefail

# Run kubernetes driver unit tests in a Docker container
# This uses the same base image as the deployed nova-compute to ensure
# compatible Python version and dependencies

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="nova-test-runner"
BASE_IMAGE="${BASE_IMAGE:-keppel.eu-de-1.cloud.sap/ccloud/loci-nova:bobcat-latest}"

# Build test image (force linux/amd64 for compatibility with nova image)
echo "Building test image..."
docker build \
    --platform linux/amd64 \
    --build-arg FROM="$BASE_IMAGE" \
    -t "$IMAGE_NAME" \
    -f "$SCRIPT_DIR/Dockerfile.test" \
    "$SCRIPT_DIR"

# Run tests using unittest discover (avoids stestr's full test discovery)
echo ""
echo "Running kubernetes driver tests..."
docker run --rm \
    --platform linux/amd64 \
    -v "$REPO_ROOT:/nova" \
    -w /nova \
    "$IMAGE_NAME" \
    python -m unittest discover -s nova/tests/unit/virt/kubernetes -v "${@}"
