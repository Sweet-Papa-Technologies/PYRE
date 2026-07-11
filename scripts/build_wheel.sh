#!/usr/bin/env bash
set -euo pipefail

profile="${1:-full}"
output="${2:-dist/${profile}}"
case "$profile" in
  full|slim) ;;
  *) echo "usage: $0 [full|slim] [output-directory]" >&2; exit 2 ;;
esac

mkdir -p "$output"
PYRE_BUILD_PROFILE="$profile" python -m pip wheel . \
  --no-deps --no-build-isolation --wheel-dir "$output"
