#!/usr/bin/env bash
# pocketic_setup.sh — idempotently fetch the PocketIC server binary.
#
# Pinned versions (keep in lockstep — see dfinity/pocketic-py CHANGELOG):
#   pip package  pocket-ic==3.1.2
#   server       13.0.0
#
# Usage:
#   ./scripts/pocketic_setup.sh          # download if missing, print export line
#   eval "$(./scripts/pocketic_setup.sh | tail -1)"   # set POCKET_IC_BIN in shell
#
# The binary is cached at ~/.cache/pocket-ic/<version>/pocket-ic; re-runs are
# no-ops. (The server insists its binary is named exactly "pocket-ic", so the
# version lives in the directory name.)

set -euo pipefail

POCKET_IC_VERSION="${POCKET_IC_VERSION:-13.0.0}"
CACHE_DIR="${POCKET_IC_CACHE_DIR:-$HOME/.cache/pocket-ic}/$POCKET_IC_VERSION"
BIN="$CACHE_DIR/pocket-ic"

# --- platform detection ------------------------------------------------------
case "$(uname -s)" in
    Darwin) os="darwin" ;;
    Linux)  os="linux" ;;
    *) echo "error: unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
    arm64|aarch64) arch="arm64" ;;
    x86_64|amd64)  arch="x86_64" ;;
    *) echo "error: unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

URL="https://github.com/dfinity/pocketic/releases/download/${POCKET_IC_VERSION}/pocket-ic-${arch}-${os}.gz"

# --- fetch (idempotent) ------------------------------------------------------
if [ -x "$BIN" ]; then
    echo "pocket-ic server $POCKET_IC_VERSION already cached at $BIN" >&2
else
    mkdir -p "$CACHE_DIR"
    echo "downloading $URL" >&2
    tmp="$(mktemp "$CACHE_DIR/.pocket-ic.XXXXXX")"
    trap 'rm -f "$tmp" "$tmp.gz"' EXIT
    curl --fail --location --silent --show-error --retry 3 -o "$tmp.gz" "$URL"
    gunzip -c "$tmp.gz" > "$tmp"
    chmod +x "$tmp"
    mv "$tmp" "$BIN"
    rm -f "$tmp.gz"
    trap - EXIT
    echo "installed $BIN" >&2
fi

# macOS: clear the quarantine bit so Gatekeeper doesn't block the binary.
if [ "$os" = "darwin" ]; then
    xattr -d com.apple.quarantine "$BIN" 2>/dev/null || true
fi

# Last line is machine-consumable: eval "$(... | tail -1)"
echo "export POCKET_IC_BIN=$BIN"
