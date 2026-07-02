#!/usr/bin/env bash
# WS-E budget-regression gate: framework instruction costs must stay under
# recorded thresholds (≈10x the measured values in DECISIONS.md — headroom
# for growth, but a silent 10x regression fails CI).
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"

MAX_BASELINE="${MAX_BASELINE:-500000}"        # trivial query (measured ~41k)
MAX_ROUTED="${MAX_ROUTED:-6000000}"           # routed GET /health (measured ~608k)
MAX_JSON_ECHO="${MAX_JSON_ECHO:-7000000}"     # /echo/{name} (measured ~676k)

get_count() { # canister method args
    dfx canister call "$1" "$2" "$3" 2>/dev/null | grep -o '[0-9_]*' | head -1 | tr -d '_'
}

fail=0
check() { # name value max
    if [[ "$2" -gt "$3" ]]; then
        echo "FAIL  $1: $2 instructions (max $3)"
        fail=1
    else
        echo "PASS  $1: $2 instructions (max $3)"
    fi
}

baseline="$(get_count phase1_spike perf_baseline '()')"
routed="$(get_count rest_api pyre_perf_probe '("/health")')"
echo_cost="$(get_count rest_api pyre_perf_probe '("/echo/budget-probe")')"

check "trivial query baseline" "$baseline" "$MAX_BASELINE"
check "routed GET /health"     "$routed"   "$MAX_ROUTED"
check "JSON echo w/ param"     "$echo_cost" "$MAX_JSON_ECHO"

exit "$fail"
