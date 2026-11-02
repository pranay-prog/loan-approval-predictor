#!/usr/bin/env bash
# Demonstrate container networking:
#  * both containers are on the user-defined bridge network loan-net
#  * the app resolves the database by container name (Podman DNS)
#  * the database is NOT published to the host - only the app is
set -uo pipefail
. "$(dirname "$0")/config.sh"

step "Networks"
run podman network ls
run podman network inspect "$NETWORK" --format '{{.Name}} {{.Driver}} {{range .Subnets}}{{.Subnet}} gw={{.Gateway}}{{end}} dns={{.DNSEnabled}}'

step "Container IP addresses on $NETWORK"
for c in "$APP_CONTAINER" "$DB_CONTAINER"; do
  printf '%-10s ' "$c"; podman inspect "$c" --format "{{(index .NetworkSettings.Networks \"$NETWORK\").IPAddress}}"
done

step "DNS: app container resolves '$DB_CONTAINER' by name"
run podman exec "$APP_CONTAINER" python -c "import socket; print('$DB_CONTAINER ->', socket.gethostbyname('$DB_CONTAINER'))"

step "TCP: app container can reach PostgreSQL on 5432"
run podman exec "$APP_CONTAINER" python -c "import socket; s=socket.create_connection(('$DB_CONTAINER',5432),3); print('connected to', s.getpeername()); s.close()"

step "Published ports (host -> container)"
run podman port "$APP_CONTAINER"
printf '%s ' "$DB_CONTAINER:"; podman port "$DB_CONTAINER" || true; echo "(none - database is private to $NETWORK)"

step "From the host: app reachable on localhost:${HOST_PORT}"
run curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://localhost:${HOST_PORT}/api/health"
ok "Networking verified"
