#!/usr/bin/env bash
# Collect diagnostics when something does not work.
# Output is also saved to logs/troubleshoot-<timestamp>.txt for the report.
set -uo pipefail
. "$(dirname "$0")/config.sh"
mkdir -p "$LOG_DIR_HOST"
OUT="$LOG_DIR_HOST/troubleshoot-$(date +%Y%m%d-%H%M%S).txt"

{
step "Podman version";            podman version --format '{{.Client.Version}}'
step "Rootless?";                 podman info --format 'rootless={{.Host.Security.Rootless}}  cgroup={{.Host.CgroupsVersion}}'
step "Containers (all)";          podman ps -a --filter name=loan --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
step "Exit codes / health";       for c in "$APP_CONTAINER" "$DB_CONTAINER"; do podman inspect "$c" --format '{{.Name}}: status={{.State.Status}} exit={{.State.ExitCode}} health={{.State.Health.Status}} restarts={{.RestartCount}}' 2>/dev/null || echo "$c: missing"; done
step "Network";                   podman network inspect "$NETWORK" --format '{{.Name}} {{range .Subnets}}{{.Subnet}}{{end}}' 2>&1
step "Volumes";                   podman volume ls --filter name=loan
step "Port 8080 on host";         (ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep ":${HOST_PORT}" || echo "nothing listening on ${HOST_PORT}"
step "HTTP health";               curl -s -m 5 "http://localhost:${HOST_PORT}/api/health" || echo "app not reachable"
step "App logs (last 40)";        podman logs --tail 40 "$APP_CONTAINER" 2>&1
step "DB logs (last 20)";         podman logs --tail 20 "$DB_CONTAINER" 2>&1
step "DB ready?";                 podman exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" 2>&1
step "Rows in predictions table"; podman exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tc "SELECT COUNT(*) FROM predictions;" 2>&1
step "Bind mount ownership";      ls -ln "$DATA_DIR_HOST" "$LOG_DIR_HOST" 2>&1 | head
} 2>&1 | tee "$OUT"

echo
ok "Saved to $OUT"
cat <<'EOF'

Common fixes
------------
* "address already in use"        -> HOST_PORT=8081 ./podman/up.sh
* app exits: "Could not connect"  -> podman start loan-db ; check DB logs above
* "Permission denied" on ./logs   -> podman unshare chown -R 1001:1001 data logs
* SELinux denials (Fedora/RHEL)   -> keep the :Z suffix on -v mounts
* changed code not visible        -> ./podman/build.sh && podman rm -f loan-app && ./podman/up.sh
* start completely fresh          -> ./podman/down.sh --purge && ./podman/up.sh
EOF
