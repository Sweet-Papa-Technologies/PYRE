#!/usr/bin/env bash
# Phase 1 determinism gate (§8): repeated outcalls through the transform
# must produce byte-identical canonical results. Also probes the raw
# (untransformed) path to document the failure mode.
#
# Local-replica caveat: a single local node can't reproduce true
# multi-replica divergence; this validates the transform mechanics and
# repeated-call stability. The mainnet run is the real gate.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"

URL="${SPIKE_URL:-https://xkcd.com/642/info.0.json}"
RUNS="${RUNS:-3}"
NETWORK="${NETWORK:-local}"

echo "== Phase 1 spike: $RUNS transformed fetches of $URL (network: $NETWORK) =="
results=()
for i in $(seq 1 "$RUNS"); do
    # flatten dfx's multi-line Candid output to one line per run
    r="$(dfx canister call phase1_spike fetch_transformed "(\"$URL\")" --network "$NETWORK" | tr -d '\n' | tr -s ' ')"
    echo "run $i: $r"
    results+=("$r")
done

unique="$(printf '%s\n' "${results[@]}" | sort -u | wc -l | tr -d ' ')"
if [[ "$unique" == "1" ]] && [[ "${results[0]}" != *"ERR:"* ]]; then
    echo "DETERMINISM GATE: PASS — $RUNS runs byte-identical post-transform"
else
    echo "DETERMINISM GATE: FAIL — $unique distinct results across $RUNS runs"
    exit 1
fi

echo
echo "== Failure-mode probe: raw (untransformed) fetches =="
raw1="$(dfx canister call phase1_spike fetch_raw "(\"$URL\")" --network "$NETWORK")"
sleep 2
raw2="$(dfx canister call phase1_spike fetch_raw "(\"$URL\")" --network "$NETWORK")"
if [[ "$raw1" == "$raw2" ]]; then
    echo "raw responses matched this time (volatile headers can still diverge on mainnet)"
else
    echo "raw responses DIFFER between calls (as expected — volatile headers):"
    diff <(echo "$raw1") <(echo "$raw2") | head -20 || true
fi
