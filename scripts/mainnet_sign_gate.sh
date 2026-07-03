#!/usr/bin/env bash
# v1.1 Phase-3 mainnet gate: a mainnet canister signs with the REAL key_1
# threshold key; the signature verifies externally; tamper is rejected.
# Also measures the real per-signature cycle cost via balance delta.
#
# Usage: scripts/mainnet_sign_gate.sh   (pyre-dev identity, rest_api on ic)
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"
export DFX_WARNING=-mainnet_plaintext_identity

REST_ID="$(dfx canister id rest_api --network ic)"
BASE="https://${REST_ID}.icp0.io"
PASS=0; FAIL=0
ok()   { echo "PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL  $1"; FAIL=$((FAIL+1)); }

balance() {
    dfx canister status rest_api --network ic --identity pyre-dev 2>/dev/null \
        | awk '/^Balance:/ {gsub(/[_,]/,"",$2); print $2; exit}'
}

echo "== mainnet sign gate (canister ${REST_ID}, key_1) =="

pub_hex="$(curl -sS -m 60 "$BASE/attest/pubkey" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["public_key_hex"])')"
[[ -n "$pub_hex" ]] && ok "public key fetched: ${pub_hex:0:16}…" || bad "no public key"

b0="$(balance)"
N=3
tokens=()
for i in $(seq 1 $N); do
    jwt="$(curl -sS -m 60 "$BASE/attest" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["jwt"])')"
    tokens+=("$jwt")
done
b1="$(balance)"
per_sign=$(( (b0 - b1) / N ))
echo "balance: $b0 -> $b1  | per-attest (incl. update): ${per_sign} cycles"

for jwt in "${tokens[@]}"; do
    if .venv-dev/bin/python scripts/verify_signature.py jwt "$jwt" "$pub_hex" >/dev/null 2>&1; then
        ok "external verify: mainnet threshold signature"
    else
        bad "external verify rejected a mainnet signature"
    fi
done
if .venv-dev/bin/python scripts/verify_signature.py jwt "${tokens[0]}" "$pub_hex" --tamper >/dev/null 2>&1; then
    ok "tampered JWT correctly rejected"
else
    bad "tampered JWT was accepted"
fi

echo; echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
