#!/usr/bin/env bash
# Walk through the container lifecycle commands, one step at a time.
# Ideal for the live demo and for report screenshots.
#   ./podman/lifecycle-demo.sh          (press Enter between steps)
#   AUTO=1 ./podman/lifecycle-demo.sh   (no pauses)
set -uo pipefail
. "$(dirname "$0")/config.sh"
pause() { [ "${AUTO:-0}" = 1 ] || read -rp $'\n[Enter] to continue...'; }

step "List running containers"
run podman ps --format "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"; pause

step "Inspect the app container (IP, mounts, ports, health)"
run podman inspect "$APP_CONTAINER" --format 'Name: {{.Name}}
State: {{.State.Status}}  Health: {{.State.Health.Status}}  StartedAt: {{.State.StartedAt}}
Image: {{.ImageName}}
Network IP: {{range $k,$v := .NetworkSettings.Networks}}{{$k}}={{$v.IPAddress}} {{end}}
Ports: {{range $p,$b := .NetworkSettings.Ports}}{{$p}}->{{range $b}}{{.HostPort}}{{end}} {{end}}
Mounts:{{range .Mounts}}
  {{.Type}}  {{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}} -> {{.Destination}}{{end}}'; pause

step "Port mapping"
run podman port "$APP_CONTAINER"; pause

step "Logs (last 15 lines)"
run podman logs --tail 15 "$APP_CONTAINER"; pause

step "Processes inside the container"
run podman top "$APP_CONTAINER"; pause

step "Resource usage"
run podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" "$APP_CONTAINER" "$DB_CONTAINER"; pause

step "Run a command inside the container (exec)"
run podman exec "$APP_CONTAINER" sh -c 'whoami; python --version; ls -l /app/models'; pause

step "Health check"
run podman healthcheck run "$APP_CONTAINER" && ok "healthy"; pause

step "Stop -> state"
run podman stop "$APP_CONTAINER"
run podman ps -a --filter name="$APP_CONTAINER" --format "{{.Names}}: {{.Status}}"; pause

step "Start again"
run podman start "$APP_CONTAINER"
sleep 6
run podman ps --filter name="$APP_CONTAINER" --format "{{.Names}}: {{.Status}}"; pause

step "Restart"
run podman restart "$APP_CONTAINER"
sleep 6
run curl -s "http://localhost:${HOST_PORT}/api/health"; echo; pause

step "Pause / unpause"
run podman pause "$APP_CONTAINER"
run podman ps --filter name="$APP_CONTAINER" --format "{{.Names}}: {{.Status}}"
run podman unpause "$APP_CONTAINER"; pause

step "Image versions available"
run podman images "$IMAGE"
ok "Lifecycle demo complete"
