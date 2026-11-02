#!/bin/sh
# Container entrypoint: prepares mounted folders, then hands over to CMD.
set -e

echo "[entrypoint] Loan Approval Predictor v${APP_VERSION} starting as $(id -un) (uid $(id -u))"

# Empty ./data bind mount on first run -> copy the bundled dataset into it
if [ ! -f "${DATA_DIR}/loan_data.csv" ]; then
  if cp /app/seed-data/loan_data.csv "${DATA_DIR}/" 2>/dev/null; then
    echo "[entrypoint] Seeded ${DATA_DIR}/loan_data.csv"
  else
    echo "[entrypoint] WARNING: ${DATA_DIR} is not writable - using built-in dataset"
    export DATA_DIR=/app/seed-data
  fi
fi

# Logs folder must be writable, otherwise log to stdout only
if ! touch "${LOG_DIR}/.write-test" 2>/dev/null; then
  echo "[entrypoint] WARNING: ${LOG_DIR} is not writable - file logging disabled"
  export LOG_DIR=/tmp/logs
else
  rm -f "${LOG_DIR}/.write-test"
fi

echo "[entrypoint] DATABASE_URL backend: $(echo "${DATABASE_URL:-sqlite}" | cut -d: -f1)"
exec "$@"
