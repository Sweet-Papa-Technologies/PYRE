#!/usr/bin/env bash
# WASM-size / idle-burn regression gate (v1.1 Phase 0): built canister
# artifacts must stay under the recorded thresholds in
# scripts/size_thresholds.env (~10% above measured baselines).
# Roadmap rationale: "Adding a fat crate fails CI on size/idle" — this gate
# is what makes Phase-2 Rust work safe to land.
#
# Idle burn ─────────────────────────────────────────────────────────────────
# ICP charges idle cycles as a function of allocated MEMORY, not traffic.
# Mainnet measurement: rest_api burns ~2.1B cycles/day at ~48 MB memory_size
# (≈44M cycles per MB per day on a 13-node subnet). Post-install memory is
# dominated by the Kybra interpreter + stdlib heap, which tracks the shipped
# WASM closely — so offline/in CI we gate on WASM size (raw + gzipped) as the
# idle-burn proxy.
#
# POCKETIC HOOK ─────────────────────────────────────────────────────────────
# The better idle-burn metric is post-install `canister_status.memory_size`
# measured in PocketIC (harness under tests/pocketic/). When that harness
# ships a scripts/pocketic_memory_check.sh, this gate invokes it below —
# wire the memory_size threshold check there.
set -euo pipefail
cd "$(dirname "$0")/.."

# Checked-in baselines/thresholds; every value is env-overridable.
source scripts/size_thresholds.env

CANISTERS="${CANISTERS:-rest_api food_tracker outbound phase1_spike}"

file_size() { wc -c < "$1" | tr -d '[:space:]'; }

fail=0
checked=0
check() { # name value max
    if [[ "$2" -gt "$3" ]]; then
        echo "FAIL  $1: $2 bytes (max $3)"
        fail=1
    else
        echo "PASS  $1: $2 bytes (max $3)"
    fi
    checked=$((checked + 1))
}

for c in $CANISTERS; do
    raw=".kybra/$c/$c.wasm"
    gz=".dfx/local/canisters/$c/$c.wasm.gz"

    if [[ ! -f "$raw" ]]; then
        echo "SKIP  $c: no build artifact at $raw"
        continue
    fi

    raw_max_var="MAX_RAW_$c"
    gz_max_var="MAX_GZ_$c"
    check "$c raw wasm"      "$(file_size "$raw")" "${!raw_max_var}"

    if [[ -f "$gz" ]]; then
        check "$c gzipped wasm" "$(file_size "$gz")" "${!gz_max_var}"
    else
        # dfx hasn't produced the shipped .gz (e.g. a kybra-only CI build):
        # measure gzip -9 of the raw wasm, which is what dfx would ship.
        check "$c gzipped wasm (gzip -9 of raw)" \
              "$(gzip -9 -c "$raw" | wc -c | tr -d '[:space:]')" "${!gz_max_var}"
    fi
done

if [[ "$checked" -eq 0 ]]; then
    # Offline fallback: exercise a deterministic package/source-footprint
    # ceiling without pretending this is a Wasm or idle-burn measurement.
    mock_size="$(find pyre -type f -name '*.py' -not -path '*/__pycache__/*' -exec wc -c {} + | awk '{s+=$1} END {print s+0}')"
    # 750 KB is ~15% above the measured full vNext source footprint. This is
    # only an integrity/regression proxy when no Wasm exists; real artifacts
    # continue to use the stricter recorded per-canister thresholds above.
    mock_max="${MAX_OFFLINE_SOURCE_BYTES:-750000}"
    echo "MOCK  no Wasm artifacts; running deterministic source-footprint fallback"
    check "PYRE Python source footprint (not Wasm/idle burn)" "$mock_size" "$mock_max"
fi

# POCKETIC HOOK — post-install memory_size is the true idle-burn input.
# See header. No-op until the pocketic harness provides this script.
if [[ -x scripts/pocketic_memory_check.sh ]]; then
    echo "== pocketic memory_size check =="
    bash scripts/pocketic_memory_check.sh || fail=1
fi

exit "$fail"
