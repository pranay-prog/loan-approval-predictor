#!/usr/bin/env bash
# Shared settings for all Podman scripts. Override any value with an env var
# or by creating podman/.env (see podman/.env.example).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
[ -f "$HERE/.env" ] && . "$HERE/.env"

APP_NAME="${APP_NAME:-loan-approval-predictor}"
VERSION="${VERSION:-1.0.0}"
IMAGE="${IMAGE:-localhost/${APP_NAME}}"

NETWORK="${NETWORK:-loan-net}"
APP_CONTAINER="${APP_CONTAINER:-loan-app}"
DB_CONTAINER="${DB_CONTAINER:-loan-db}"
DB_IMAGE="${DB_IMAGE:-docker.io/library/postgres:16-alpine}"

MODEL_VOLUME="${MODEL_VOLUME:-loan-models}"
DB_VOLUME="${DB_VOLUME:-loan-pgdata}"
DATA_DIR_HOST="${DATA_DIR_HOST:-$PROJECT_ROOT/data}"
LOG_DIR_HOST="${LOG_DIR_HOST:-$PROJECT_ROOT/logs}"

HOST_PORT="${HOST_PORT:-8080}"
APP_PORT=5000

DB_USER="${DB_USER:-loanuser}"
DB_PASSWORD="${DB_PASSWORD:-loanpass}"
DB_NAME="${DB_NAME:-loans}"

# Registry used by push.sh (quay.io or docker.io)
REGISTRY="${REGISTRY:-quay.io}"
REGISTRY_USER="${REGISTRY_USER:-your-username}"

# Pretty output
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
run()  { printf '\033[0;36m$ %s\033[0m\n' "$*"; "$@"; }
ok()   { printf '\033[0;32m✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[0;33m! %s\033[0m\n' "$*"; }
