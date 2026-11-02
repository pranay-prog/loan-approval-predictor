#!/usr/bin/env bash
# Build the custom image from the Containerfile and tag it with a version.
#   ./podman/build.sh            -> loan-approval-predictor:1.0.0 + :latest
#   VERSION=1.1.0 ./podman/build.sh
set -euo pipefail
. "$(dirname "$0")/config.sh"
cd "$PROJECT_ROOT"

step "Building ${IMAGE}:${VERSION} from Containerfile"
run podman build \
  --format docker \
  --build-arg APP_VERSION="$VERSION" \
  -t "${IMAGE}:${VERSION}" \
  -t "${IMAGE}:latest" \
  -f Containerfile .

step "Image built"
run podman images "${IMAGE}"
run podman image history "${IMAGE}:${VERSION}" --format "table {{.CreatedBy}}\t{{.Size}}" | head -20
run podman inspect "${IMAGE}:${VERSION}" --format 'User={{.Config.User}}  Ports={{.Config.ExposedPorts}}  Volumes={{.Config.Volumes}}'
ok "Next: ./podman/up.sh"
