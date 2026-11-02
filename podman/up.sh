#!/usr/bin/env bash
# Create the network + volumes and start both containers.
#   loan-db  : PostgreSQL (no host port, reachable only on loan-net)
#   loan-app : our custom image, published on http://localhost:8080
set -euo pipefail
. "$(dirname "$0")/config.sh"

if ! podman image exists "${IMAGE}:${VERSION}"; then
  warn "Image ${IMAGE}:${VERSION} not found - building it first"
  "$HERE/build.sh"
fi

step "1/5 Podman network"
podman network exists "$NETWORK" || run podman network create --driver bridge "$NETWORK"
run podman network inspect "$NETWORK" --format '{{.Name}}  driver={{.Driver}}  subnet={{range .Subnets}}{{.Subnet}}{{end}}'

step "2/5 Persistent storage"
podman volume exists "$DB_VOLUME"    || run podman volume create "$DB_VOLUME"
podman volume exists "$MODEL_VOLUME" || run podman volume create "$MODEL_VOLUME"
mkdir -p "$DATA_DIR_HOST" "$LOG_DIR_HOST"
# The app runs as uid 1001 inside the container. In rootless Podman, give that
# uid ownership of the bind-mounted folders (DO188: podman unshare chown).
if [ "$(id -u)" -eq 0 ]; then
  chown -R 1001:1001 "$DATA_DIR_HOST" "$LOG_DIR_HOST" || true
else
  podman unshare chown -R 1001:1001 "$DATA_DIR_HOST" "$LOG_DIR_HOST" 2>/dev/null \
    || warn "Could not chown bind mounts (fine on macOS/Windows podman machine)"
fi
run podman volume ls --filter name=loan

step "3/5 Database container ($DB_CONTAINER)"
if podman container exists "$DB_CONTAINER"; then
  run podman start "$DB_CONTAINER"
else
  run podman run -d \
    --name "$DB_CONTAINER" \
    --network "$NETWORK" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -e POSTGRES_DB="$DB_NAME" \
    -v "$DB_VOLUME":/var/lib/postgresql/data:Z \
    --health-cmd "pg_isready -U $DB_USER -d $DB_NAME" \
    --health-interval 10s --health-retries 5 \
    --restart on-failure \
    "$DB_IMAGE"
fi
printf 'Waiting for PostgreSQL'
for _ in $(seq 1 30); do
  if podman exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then echo; ok "PostgreSQL ready"; break; fi
  printf '.'; sleep 2
done

step "4/5 Application container ($APP_CONTAINER)"
if podman container exists "$APP_CONTAINER"; then
  run podman start "$APP_CONTAINER"
else
  run podman run -d \
    --name "$APP_CONTAINER" \
    --network "$NETWORK" \
    -p "${HOST_PORT}:${APP_PORT}" \
    -e DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_CONTAINER}:5432/${DB_NAME}" \
    -v "$MODEL_VOLUME":/app/models:Z \
    -v "$DATA_DIR_HOST":/app/data:Z \
    -v "$LOG_DIR_HOST":/app/logs:Z \
    --restart on-failure \
    "${IMAGE}:${VERSION}"
fi

step "5/5 Waiting for the app to become healthy"
for _ in $(seq 1 40); do
  if curl -fsS "http://localhost:${HOST_PORT}/api/health" >/dev/null 2>&1; then
    echo; ok "App is up!"; break
  fi
  printf '.'; sleep 2
done
echo
run podman ps --filter name=loan --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
curl -s "http://localhost:${HOST_PORT}/api/health" || warn "Health check failed - run ./podman/troubleshoot.sh"
echo
ok "Open http://localhost:${HOST_PORT} in your browser"
