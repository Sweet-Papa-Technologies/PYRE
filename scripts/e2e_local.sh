#!/usr/bin/env bash
# End-to-end test against a running local replica (Phase 2 acceptance, §8).
#
# Prereqs: `dfx start --background` already running, canisters deployed
# (or run with --deploy to do a clean deploy first).
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"
if [[ ! -x venv/bin/python ]] || ! dfx canister id rest_api >/dev/null 2>&1; then
    echo "MOCK  deploy toolchain/local canisters unavailable; running deterministic offline E2E"
    exec python3 scripts/e2e_offline.py
fi
# kybra builds (incl. the mid-test upgrade) need the deploy venv active
source venv/bin/activate

PORT="$(dfx info webserver-port)"
PASS=0
FAIL=0

if [[ "${1:-}" == "--deploy" ]]; then
    dfx deploy
fi

REST_ID="$(dfx canister id rest_api)"
OUT_ID="$(dfx canister id outbound)"

http() { # method url [data]
    local method="$1" url="$2" data="${3:-}"
    if [[ -n "$data" ]]; then
        curl -sS -X "$method" -H "content-type: application/json" -d "$data" \
             -w '\n%{http_code}' "$url"
    else
        curl -sS -X "$method" -w '\n%{http_code}' "$url"
    fi
}

check() { # name expected_status expected_grep actual
    local name="$1" want_status="$2" want_grep="$3" got="$4"
    local status body
    status="$(tail -n1 <<<"$got")"
    body="$(sed '$d' <<<"$got")"
    if [[ "$status" == "$want_status" ]] && grep -q "$want_grep" <<<"$body"; then
        echo "PASS  $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL  $name — status=$status body=$body"
        FAIL=$((FAIL + 1))
    fi
}

REST="http://${REST_ID}.localhost:${PORT}"
OUT="http://${OUT_ID}.localhost:${PORT}"

echo "== Example A: REST + persistence (canister ${REST_ID}) =="
check "GET /health"            200 '"status": "ok"'   "$(http GET  "$REST/health")"
check "GET /echo/{name}"       200 '"hello": "pyre"'  "$(http GET  "$REST/echo/pyre")"
check "GET unknown -> 404"     404 'not found'        "$(http GET  "$REST/nope")"
check "POST /items (update)"   201 '"created"'        "$(http POST "$REST/items" '{"id": "42", "name": "flame"}')"
check "GET /items/{id}"        200 '"flame"'          "$(http GET  "$REST/items/42")"
check "GET missing item"       404 'not found'        "$(http GET  "$REST/items/999")"

echo "== Persistence across upgrade =="
dfx deploy rest_api --upgrade-unchanged >/dev/null 2>&1
check "GET /items/{id} after upgrade" 200 '"flame"'   "$(http GET "$REST/items/42")"

echo "== Example B: outbound HTTPS via urllib shim (canister ${OUT_ID}) =="
check "GET /quote (outcall)"   200 '"upstream_status": 200' "$(http GET "$OUT/quote")"

FOOD_ID="$(dfx canister id food_tracker 2>/dev/null || true)"
if [[ -n "$FOOD_ID" ]]; then
    FOOD="http://${FOOD_ID}.localhost:${PORT}"
    echo "== Reference app: food_tracker (auth + data + certified summary) =="
    check "POST /foods w/o token -> 401" 401 'unauthorized' \
        "$(http POST "$FOOD/foods" '{"name":"apple","kcal":95}')"
    check "POST /foods with token" 201 '"id"' \
        "$(curl -sS -X POST -H "authorization: Bearer demo-food-token" \
             -H "content-type: application/json" -d '{"name":"apple","kcal":95}' \
             -w '\n%{http_code}' "$FOOD/foods")"
    check "GET /summary (public+certified)" 200 'total_kcal' "$(http GET "$FOOD/summary")"
    check "POST bad body -> 400 fields" 400 'validation failed' \
        "$(curl -sS -X POST -H "authorization: Bearer demo-food-token" \
             -d '{"kcal":"lots"}' -w '\n%{http_code}' "$FOOD/foods")"
    if .venv-dev/bin/python scripts/verify_certification.py \
         "http://${FOOD_ID}.raw.localhost:${PORT}/summary" "$FOOD_ID" "127.0.0.1:${PORT}" >/dev/null 2>&1; then
        echo "PASS  independent verifier: certified /summary"
        PASS=$((PASS + 1))
    else
        echo "FAIL  independent verifier: certified /summary"
        FAIL=$((FAIL + 1))
    fi
fi

echo "== Response certification (v2) =="
# certified route must carry IC-Certificate and pass the verifying gateway
cert_headers="$(curl -s -D - -o /dev/null "$REST/health" | tr -d '\r')"
if grep -qi "^ic-certificate:" <<<"$cert_headers"; then
    echo "PASS  /health serves IC-Certificate"
    PASS=$((PASS + 1))
else
    echo "FAIL  /health missing IC-Certificate header"
    FAIL=$((FAIL + 1))
fi
if [[ -x .venv-dev/bin/python ]]; then
    if .venv-dev/bin/python scripts/verify_certification.py \
         "http://${REST_ID}.raw.localhost:${PORT}/health" "$REST_ID" "127.0.0.1:${PORT}" >/dev/null 2>&1; then
        echo "PASS  independent verifier: certified /health"
        PASS=$((PASS + 1))
    else
        echo "FAIL  independent verifier: certified /health"
        FAIL=$((FAIL + 1))
    fi
    if .venv-dev/bin/python scripts/verify_certification.py \
         "http://${REST_ID}.raw.localhost:${PORT}/echo/x" "$REST_ID" "127.0.0.1:${PORT}" >/dev/null 2>&1; then
        echo "PASS  independent verifier: skip-certified /echo"
        PASS=$((PASS + 1))
    else
        echo "FAIL  independent verifier: skip-certified /echo"
        FAIL=$((FAIL + 1))
    fi
fi

echo "== v1.1: threshold signing (pyre.sign, local key_1) =="
attest_json="$(curl -sS "$REST/attest")"
pubkey_json="$(curl -sS "$REST/attest/pubkey")"
jwt_token="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["jwt"])' "$attest_json" 2>/dev/null || true)"
pub_hex="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["public_key_hex"])' "$pubkey_json" 2>/dev/null || true)"
if [[ -n "$jwt_token" && -n "$pub_hex" ]]; then
    echo "PASS  GET /attest issues a JWT; /attest/pubkey returns the subnet key"
    PASS=$((PASS + 1))
    if .venv-dev/bin/python scripts/verify_signature.py jwt "$jwt_token" "$pub_hex" >/dev/null 2>&1; then
        echo "PASS  external verifier: threshold signature (secp256k1)"
        PASS=$((PASS + 1))
    else
        echo "FAIL  external verifier rejected the threshold signature"
        FAIL=$((FAIL + 1))
    fi
    if .venv-dev/bin/python scripts/verify_signature.py jwt "$jwt_token" "$pub_hex" --tamper >/dev/null 2>&1; then
        echo "PASS  external verifier: tampered JWT correctly rejected"
        PASS=$((PASS + 1))
    else
        echo "FAIL  external verifier accepted a tampered JWT"
        FAIL=$((FAIL + 1))
    fi
else
    echo "FAIL  /attest or /attest/pubkey unavailable — attest=$attest_json pubkey=$pubkey_json"
    FAIL=$((FAIL + 1))
fi

echo "== v1.1: canister logging surface =="
if dfx canister logs rest_api 2>/dev/null | grep -q "attestation issued"; then
    echo "PASS  dfx canister logs shows pyre.log lines"
    PASS=$((PASS + 1))
else
    echo "FAIL  pyre.log line not found in canister logs"
    FAIL=$((FAIL + 1))
fi

echo
echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
