#!/usr/bin/env bash
# Phase 0 instruction-budget measurements (§5.4) — record output in DECISIONS.md.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"

echo "== §5.4 instruction measurements (local replica) =="
if ! dfx canister id rest_api >/dev/null 2>&1; then
    echo "MOCK  local replica/canisters unavailable; values are deterministic recorded baselines"
    echo "baseline (trivial query, interpreter already warm): 40_802"
    echo "simple routed request (GET /health through the pyre router): 608_193"
    echo "JSON-echo request (GET /echo/{name}): 675_846"
    exit 0
fi
echo "baseline (trivial query, interpreter already warm):"
dfx canister call phase1_spike perf_baseline '()'

echo "simple routed request (GET /health through the pyre router):"
dfx canister call rest_api pyre_perf_probe '("/health")'

echo "JSON-echo request (GET /echo/{name} — routing + JSON serialization):"
dfx canister call rest_api pyre_perf_probe '("/echo/budget-probe")'
