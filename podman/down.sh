#!/usr/bin/env bash
# Stop and remove the containers.
#   ./podman/down.sh          -> keeps volumes (data survives)
#   ./podman/down.sh --purge  -> also deletes volumes and the network
set -euo pipefail
. "$(dirname "$0")/config.sh"

step "Stopping containers"
for c in "$APP_CONTAINER" "$DB_CONTAINER"; do
  podman container exists "$c" && run podman stop -t 10 "$c" && run podman rm "$c" || true
done

if [ "${1:-}" = "--purge" ]; then
  step "Removing volumes and network (ALL DATA WILL BE LOST)"
  run podman volume rm -f "$DB_VOLUME" "$MODEL_VOLUME" || true
  run podman network rm -f "$NETWORK" || true
else
  ok "Volumes kept: $DB_VOLUME, $MODEL_VOLUME  (use --purge to delete)"
fi
run podman ps -a --filter name=loan
