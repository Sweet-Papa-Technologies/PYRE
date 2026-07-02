#!/usr/bin/env bash
# build_native.sh — build a Kybra canister WITH the _pyre_native crypto module.
#
# Kybra regenerates the Rust project under .kybra/<canister>/ on every build
# (kybra_generate), so _pyre_native is wired in as a scripted POST-GENERATE
# patch, then cargo is re-run for the final wasm:
#
#   1. normal dfx build          -> regenerates + compiles .kybra/<canister>/
#   2. patch the generated crate -> copy pyre_native/src/pyre_native.rs in,
#                                   inject crate deps (pyre_native/Cargo.toml
#                                   KYBRA-INJECT block) under [dependencies],
#                                   declare `mod pyre_native;` and register
#                                   the module on both VM constructions
#                                   (init + post_upgrade)
#   3. re-run cargo + wasi2ic    -> final wasm at .kybra/<c>/<c>.wasm, which
#                                   is exactly where dfx expects it
#   4. (--install) dfx canister install --mode auto --wasm <that wasm>
#
# The re-run is cheap: the warm CARGO_TARGET_DIR means only the AEAD crates
# and the canister crate itself recompile (~5s), and the .did is unchanged
# because the patch adds no canister methods.
#
# Usage: scripts/build_native.sh <canister_name> [--install]
# Requires: the PYRE deploy venv active is NOT needed here (dfx invokes it
# itself via dfx.json), but dfx must be on PATH and, for --install, the
# local replica must be running with the canister created.
set -euo pipefail
cd "$(dirname "$0")/.."

CANISTER="${1:?usage: scripts/build_native.sh <canister_name> [--install]}"
INSTALL="${2:-}"

KYBRA_RUST_VERSION="${KYBRA_RUST_VERSION:-1.87.0}"
KYBRA_RUST_DIR="$HOME/.config/kybra/rust/$KYBRA_RUST_VERSION"
KYBRA_BIN="$KYBRA_RUST_DIR/bin"
export CARGO_TARGET_DIR="$HOME/.config/kybra/rust/target"
export CARGO_HOME="$KYBRA_RUST_DIR"
export RUSTUP_HOME="$KYBRA_RUST_DIR"

GEN=".kybra/$CANISTER"

echo "== [1/4] normal kybra build (dfx build $CANISTER) =="
dfx canister create "$CANISTER" >/dev/null 2>&1 || true
dfx build "$CANISTER"

echo "== [2/4] patching generated crate with _pyre_native =="
cp pyre_native/src/pyre_native.rs "$GEN/src/pyre_native.rs"
python3 - "$GEN" <<'EOF'
import re, sys

gen = sys.argv[1]

# -- Cargo.toml: inject the pinned crypto deps under [dependencies] --------
inject = re.search(
    r"# BEGIN KYBRA-INJECT.*?\n(.*?)# END KYBRA-INJECT",
    open("pyre_native/Cargo.toml").read(),
    re.S,
).group(1)
path = f"{gen}/Cargo.toml"
toml = open(path).read()
if "aes-gcm" not in toml:
    toml = toml.replace("[dependencies]\n", "[dependencies]\n" + inject, 1)
    open(path, "w").write(toml)

# -- src/lib.rs: declare the module and register it on both VMs ------------
path = f"{gen}/src/lib.rs"
src = open(path).read()
if "mod pyre_native;" not in src:
    src = src.replace(
        "#![allow(warnings, unused)]",
        "#![allow(warnings, unused)]\nmod pyre_native;",
        1,
    )
    needle = "vm.add_native_modules(rustpython_stdlib::get_module_inits());\n"
    reg = (
        '        vm.add_native_module("_pyre_native".to_owned(), '
        "Box::new(crate::pyre_native::_pyre_native::make_module) "
        "as rustpython_vm::stdlib::StdlibInitFunc);\n"
    )
    count = src.count(needle)
    if count != 2:
        raise SystemExit(
            f"expected exactly 2 VM constructions (init + post_upgrade) in "
            f"{path}, found {count} — kybra_generate output changed shape; "
            f"refusing to patch blindly"
        )
    src = src.replace(needle, needle + reg)
    open(path, "w").write(src)
print("patched OK")
EOF

echo "== [3/4] rebuilding wasm with _pyre_native =="
"$KYBRA_BIN/cargo" build \
    "--manifest-path=$GEN/Cargo.toml" \
    --target=wasm32-wasip1 \
    "--package=$CANISTER" \
    --release
cp "$CARGO_TARGET_DIR/wasm32-wasip1/release/$CANISTER.wasm" "$GEN/$CANISTER.wasm"
"$KYBRA_BIN/wasi2ic" "$GEN/$CANISTER.wasm" "$GEN/$CANISTER.wasm"
echo "built $GEN/$CANISTER.wasm ($(wc -c < "$GEN/$CANISTER.wasm" | tr -d '[:space:]') bytes)"

if [[ "$INSTALL" == "--install" ]]; then
    echo "== [4/4] installing patched wasm =="
    dfx canister install "$CANISTER" --mode auto --wasm "$GEN/$CANISTER.wasm" --yes
else
    echo "== [4/4] skipped install (pass --install to deploy the patched wasm) =="
fi
