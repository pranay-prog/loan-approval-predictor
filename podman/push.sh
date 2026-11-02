#!/usr/bin/env bash
# Push the image to a public registry and pull it back.
#   REGISTRY_USER=myname ./podman/push.sh                 (quay.io)
#   REGISTRY=docker.io REGISTRY_USER=myname ./podman/push.sh
# After the first push on quay.io, open the repository settings and make it Public.
set -euo pipefail
. "$(dirname "$0")/config.sh"

if [ "$REGISTRY_USER" = "your-username" ]; then
  echo "Set REGISTRY_USER (e.g. REGISTRY_USER=pranayjain ./podman/push.sh)"; exit 1
fi
REMOTE="${REGISTRY}/${REGISTRY_USER}/${APP_NAME}"

step "Login to $REGISTRY"
run podman login "$REGISTRY"

step "Tag local image for the registry"
run podman tag "${IMAGE}:${VERSION}" "${REMOTE}:${VERSION}"
run podman tag "${IMAGE}:${VERSION}" "${REMOTE}:latest"
run podman images "$REMOTE"

step "Push"
run podman push "${REMOTE}:${VERSION}"
run podman push "${REMOTE}:latest"

step "Verify: remove local copy and pull it back"
run podman rmi "${REMOTE}:${VERSION}" "${REMOTE}:latest"
run podman pull "${REMOTE}:${VERSION}"
run podman images "$REMOTE"

ok "Public image: https://${REGISTRY}/repository/${REGISTRY_USER}/${APP_NAME}  (quay) or https://hub.docker.com/r/${REGISTRY_USER}/${APP_NAME} (docker hub)"
ok "Anyone can run it with: podman run -d -p 8080:5000 ${REMOTE}:${VERSION}"
