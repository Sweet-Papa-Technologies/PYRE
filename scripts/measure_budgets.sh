#!/usr/bin/env bash
# Phase 0 instruction-budget measurements (§5.4) — record output in DECISIONS.md.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"

echo "== §5.4 instruction measurements (local replica) =="
echo "baseline (trivial query, interpreter already warm):"
dfx canister call phase1_spike perf_baseline '()'

echo "simple routed request (GET /health through the pyre router):"
dfx canister call rest_api pyre_perf_probe '("/health")'

echo "JSON-echo request (GET /echo/{name} — routing + JSON serialization):"
dfx canister call rest_api pyre_perf_probe '("/echo/budget-probe")'
