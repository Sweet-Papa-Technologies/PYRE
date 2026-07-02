#!/usr/bin/env bash
# Safe mainnet teardown: withdraw → confirm → delete (WS-E).
#
# The $0.90 lesson (DECISIONS.md): deleting a canister whose balance can't
# fund the temporary withdrawal wallet BURNS the remaining cycles. This
# script checks each canister's balance first and refuses the lossy path
# unless FORCE_BURN=1.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"
export DFX_WARNING=-mainnet_plaintext_identity
IDENT=(--identity pyre-dev)

# Withdrawal needs a temp wallet installed in the canister first (~200B safe floor).
MIN_WITHDRAWABLE=200000000000

echo "This deletes MAINNET canisters after withdrawing their cycles."
echo "Ledger before: $(dfx cycles balance --network ic "${IDENT[@]}" 2>/dev/null)"

for canister in "$@"; do
    balance="$(dfx canister status "$canister" --network ic "${IDENT[@]}" 2>&1 \
        | awk '/^Balance:/ {gsub(/_/, "", $2); print $2}')"
    echo "== $canister: balance ${balance:-unknown} cycles"
    if [[ -z "$balance" ]]; then
        echo "   cannot read status — skipping"
        continue
    fi
    if [[ "$balance" -lt "$MIN_WITHDRAWABLE" && "${FORCE_BURN:-0}" != "1" ]]; then
        echo "   balance below ${MIN_WITHDRAWABLE} — withdrawal would fail and the"
        echo "   remainder would BURN. Top it up first (dfx cycles top-up), or"
        echo "   re-run with FORCE_BURN=1 to accept the loss. Skipping."
        continue
    fi
    dfx canister stop "$canister" --network ic "${IDENT[@]}"
    dfx canister delete "$canister" --network ic "${IDENT[@]}" --yes
done

echo "Ledger after: $(dfx cycles balance --network ic "${IDENT[@]}" 2>/dev/null)"
