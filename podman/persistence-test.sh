#!/usr/bin/env bash
# Prove that data survives container removal:
#  1. save a prediction   2. DELETE both containers   3. recreate them
#  4. the prediction is still there (PostgreSQL data lives on the loan-pgdata volume)
set -euo pipefail
. "$(dirname "$0")/config.sh"
URL="http://localhost:${HOST_PORT}"

step "1. Save a prediction"
NAME="Persistence-$(date +%H%M%S)"
run curl -s -X POST "$URL/api/predict" -H "Content-Type: application/json" -d "{
  \"applicant_name\":\"$NAME\",\"Gender\":\"Male\",\"Married\":\"Yes\",\"Dependents\":\"0\",
  \"Education\":\"Graduate\",\"Self_Employed\":\"No\",\"ApplicantIncome\":6000,\"CoapplicantIncome\":0,
  \"LoanAmount\":120,\"Loan_Amount_Term\":360,\"Credit_History\":1,\"Property_Area\":\"Urban\",\"source\":\"api\"}" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("saved id", d["id"], d["decision"])'
BEFORE=$(curl -s "$URL/api/stats" | python3 -c 'import sys,json; print(json.load(sys.stdin)["total"])')
ok "Predictions stored: $BEFORE"

step "2. Remove BOTH containers (volumes are kept)"
run podman rm -f "$APP_CONTAINER" "$DB_CONTAINER"
run podman volume ls --filter name=loan

step "3. Recreate the containers"
"$HERE/up.sh" >/dev/null
ok "Containers recreated"

step "4. Check the data is still there"
AFTER=$(curl -s "$URL/api/stats" | python3 -c 'import sys,json; print(json.load(sys.stdin)["total"])')
run curl -s "$URL/api/predictions?search=$NAME" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("found:", [(i["id"], i["applicant_name"]) for i in d["items"]])'
if [ "$AFTER" -ge "$BEFORE" ]; then ok "PERSISTENCE OK: $BEFORE before -> $AFTER after"; else warn "Data lost ($BEFORE -> $AFTER)"; exit 1; fi
step "Bind-mounted log file on the host"
run tail -n 5 "$LOG_DIR_HOST/app.log" || true
