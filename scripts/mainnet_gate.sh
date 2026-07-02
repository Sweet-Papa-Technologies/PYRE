#!/usr/bin/env bash
# Phase 1 mainnet determinism gate (STEP 3 of the mainnet run).
#
# a) CONTROL   — body-nondeterministic endpoint (per-replica uuid) through the
#                header-only transform: consensus MUST fail; we capture the
#                reject text verbatim.
# b) FIX       — same endpoint through spike_json_transform with the volatile
#                field blanked: 3 runs must be byte-identical.
# c) REALISTIC — a real public JSON API with volatile fields normalized.
#
# Prereqs: canisters deployed with `dfx deploy --network ic --identity pyre-dev`.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"
export DFX_WARNING=-mainnet_plaintext_identity
IDENT=(--identity pyre-dev)
NETWORK="${NETWORK:-ic}"

CONTROL_URL="${CONTROL_URL:-https://httpbingo.org/uuid}"
CONTROL_FIELDS="${CONTROL_FIELDS:-uuid}"
REALISTIC_URL="${REALISTIC_URL:-https://api64.ipify.org/?format=json}"
REALISTIC_FIELDS="${REALISTIC_FIELDS:-ip}"

call() { # method args...
    dfx canister call phase1_spike "$1" "$2" --network "$NETWORK" "${IDENT[@]}" 2>&1 \
        | grep -v '^WARNING' | tr -d '\n' | tr -s ' '
}

runs_identical() { # method args label
    local results=()
    for i in 1 2 3; do
        local r
        r="$(call "$1" "$2")"
        echo "  run $i: ${r:0:160}"
        results+=("$r")
    done
    local unique
    unique="$(printf '%s\n' "${results[@]}" | sort -u | wc -l | tr -d ' ')"
    if [[ "$unique" == "1" && "${results[0]}" != *"ERR:"* ]]; then
        echo "  → PASS ($3: 3 runs byte-identical)"
        return 0
    fi
    echo "  → FAIL ($3: $unique distinct results)"
    return 1
}

echo "== (a) CONTROL: $CONTROL_URL via header-only transform — consensus SHOULD fail =="
control_result="$(call fetch_transformed "(\"$CONTROL_URL\")")"
echo "  result: $control_result"
if [[ "$control_result" == *"ERR:"* ]]; then
    echo "  → EXPECTED FAILURE captured (record the reject text above in DECISIONS.md)"
else
    echo "  → WARNING: control did NOT fail — endpoint may have returned identical"
    echo "    bodies to all replicas this round; re-run, or the subnet is not replicated."
fi

echo
echo "== (b) FIX: same endpoint via spike_json_transform (blank: $CONTROL_FIELDS) =="
runs_identical fetch_json_normalized "(\"$CONTROL_URL\", \"$CONTROL_FIELDS\")" "control+body-normalize"
fix_ok=$?

echo
echo "== (c) REALISTIC: $REALISTIC_URL (blank: $REALISTIC_FIELDS) =="
runs_identical fetch_json_normalized "(\"$REALISTIC_URL\", \"$REALISTIC_FIELDS\")" "realistic"
realistic_ok=$?

echo
if [[ "$fix_ok" == 0 && "$realistic_ok" == 0 && "$control_result" == *"ERR:"* ]]; then
    echo "DETERMINISM GATE (mainnet): FULL PASS"
else
    echo "DETERMINISM GATE (mainnet): INCOMPLETE — see above"
    exit 1
fi
