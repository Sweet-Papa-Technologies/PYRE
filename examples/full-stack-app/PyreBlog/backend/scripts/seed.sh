#!/usr/bin/env bash
# Load the demo posts (idempotent). BASE/TOKEN as in smoke.sh.
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:-pyrepress-dev-token}"
curl -fsS -X POST -H "Authorization: Bearer ${TOKEN}" "${BASE}/api/seed"
echo
