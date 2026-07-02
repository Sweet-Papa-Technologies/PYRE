#!/usr/bin/env bash
# STEP 4 — real cycle burn on mainnet, measured by canister-balance deltas.
# Prereqs: canisters deployed to mainnet; jq not required (python3 used).
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"
export DFX_WARNING=-mainnet_plaintext_identity
IDENT=(--identity pyre-dev)

N_QUERY="${N_QUERY:-20}"
N_UPDATE="${N_UPDATE:-10}"
N_OUTCALL="${N_OUTCALL:-5}"

balance() { # canister
    dfx canister status "$1" --network ic "${IDENT[@]}" 2>&1 \
        | awk '/^Balance:/ {gsub(/_/, "", $2); print $2}'
}

status_line() { # canister pattern
    dfx canister status "$1" --network ic "${IDENT[@]}" 2>&1 | grep -E "$2" || true
}

REST_ID="$(dfx canister id rest_api --network ic "${IDENT[@]}" 2>/dev/null)"
OUT_ID="$(dfx canister id outbound --network ic "${IDENT[@]}" 2>/dev/null)"
REST="https://${REST_ID}.raw.icp0.io"
OUT="https://${OUT_ID}.raw.icp0.io"

echo "== canister facts =="
echo "rest_api: $REST_ID   outbound: $OUT_ID"
status_line rest_api "Memory Size|Idle cycles"
status_line outbound "Memory Size|Idle cycles"

echo
echo "== per-QUERY cost ($N_QUERY x GET /health) =="
b0="$(balance rest_api)"
for _ in $(seq 1 "$N_QUERY"); do curl -s -o /dev/null --max-time 30 "$REST/health"; done
b1="$(balance rest_api)"
echo "balance: $b0 -> $b1  | per-query: $(( (b0 - b1) / N_QUERY )) cycles"

echo
echo "== per-UPDATE cost ($N_UPDATE x POST /items) =="
b0="$(balance rest_api)"
for i in $(seq 1 "$N_UPDATE"); do
    curl -s -o /dev/null --max-time 60 -X POST -H "content-type: application/json" \
         -d "{\"id\": \"cost-$i\", \"n\": $i}" "$REST/items"
done
b1="$(balance rest_api)"
echo "balance: $b0 -> $b1  | per-update: $(( (b0 - b1) / N_UPDATE )) cycles"

echo
echo "== per-OUTCALL cost ($N_OUTCALL x GET /quote, max_response_bytes=8192) =="
b0="$(balance outbound)"
for _ in $(seq 1 "$N_OUTCALL"); do curl -s -o /dev/null --max-time 120 "$OUT/quote"; done
b1="$(balance outbound)"
echo "balance: $b0 -> $b1  | per-outcall request (incl. update): $(( (b0 - b1) / N_OUTCALL )) cycles"

echo
echo "== outcall AMPLIFICATION (how many times the target server is hit) =="
TOKEN="$(curl -s -X POST https://webhook.site/token | python3 -c 'import json,sys; print(json.load(sys.stdin)["uuid"])')"
echo "webhook.site token: $TOKEN"
dfx canister call phase1_spike fetch_transformed "(\"https://webhook.site/$TOKEN\")" \
    --network ic "${IDENT[@]}" >/dev/null 2>&1 || true
sleep 5
HITS="$(curl -s "https://webhook.site/token/$TOKEN/requests?per_page=100" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["total"])')"
echo "one canister outcall -> $HITS upstream requests (= replica count on the subnet)"
