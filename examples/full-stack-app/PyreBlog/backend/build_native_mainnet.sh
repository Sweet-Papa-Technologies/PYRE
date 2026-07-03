#!/usr/bin/env bash
# Build the pyrepress canister WITH _pyre_native (RSA/EC for pyre.oidc) and
# upgrade it on MAINNET. Same 3-edit post-generate patch as the root
# scripts/build_native.sh, adapted to this app's own dfx.json + the repo-root
# pyre_native/ source, installing over the network with the pyre-dev identity.
set -euo pipefail
cd "$(dirname "$0")"

ROOT=/Users/fterry/code/PYRE
CANISTER=pyrepress
export PATH="$HOME/Library/Application Support/org.dfinity.dfx/bin:$PATH"
export DFX_WARNING=-mainnet_plaintext_identity
source .venv/bin/activate

KYBRA_RUST_DIR="$HOME/.config/kybra/rust/1.87.0"
KYBRA_BIN="$KYBRA_RUST_DIR/bin"
export CARGO_TARGET_DIR="$HOME/.config/kybra/rust/target"
export CARGO_HOME="$KYBRA_RUST_DIR"
export RUSTUP_HOME="$KYBRA_RUST_DIR"
GEN=".kybra/$CANISTER"

echo "== [1/4] kybra build (generates $GEN) =="
dfx build "$CANISTER" --network ic

echo "== [2/4] patch generated crate with _pyre_native (from repo root) =="
cp "$ROOT/pyre_native/src/pyre_native.rs" "$GEN/src/pyre_native.rs"
python3 - "$GEN" "$ROOT" <<'EOF'
import re, sys
gen, root = sys.argv[1], sys.argv[2]
inject = re.search(r"# BEGIN KYBRA-INJECT.*?\n(.*?)# END KYBRA-INJECT",
                   open(f"{root}/pyre_native/Cargo.toml").read(), re.S).group(1)
p = f"{gen}/Cargo.toml"; toml = open(p).read()
if "aes-gcm" not in toml:
    open(p, "w").write(toml.replace("[dependencies]\n", "[dependencies]\n" + inject, 1))
p = f"{gen}/src/lib.rs"; src = open(p).read()
if "mod pyre_native;" not in src:
    src = src.replace("#![allow(warnings, unused)]",
                      "#![allow(warnings, unused)]\nmod pyre_native;", 1)
    needle = "vm.add_native_modules(rustpython_stdlib::get_module_inits());\n"
    reg = ('        vm.add_native_module("_pyre_native".to_owned(), '
           "Box::new(crate::pyre_native::_pyre_native::make_module) "
           "as rustpython_vm::stdlib::StdlibInitFunc);\n")
    n = src.count(needle)
    if n != 2:
        raise SystemExit(f"expected 2 VM constructions, found {n} — refusing to patch")
    open(p, "w").write(src.replace(needle, needle + reg))
print("patched OK")
EOF

echo "== [3/4] rebuild wasm with _pyre_native =="
"$KYBRA_BIN/cargo" build --manifest-path="$GEN/Cargo.toml" \
    --target=wasm32-wasip1 --package="$CANISTER" --release
cp "$CARGO_TARGET_DIR/wasm32-wasip1/release/$CANISTER.wasm" "$GEN/$CANISTER.wasm"
"$KYBRA_BIN/wasi2ic" "$GEN/$CANISTER.wasm" "$GEN/$CANISTER.wasm"
echo "built $(wc -c < "$GEN/$CANISTER.wasm" | tr -d '[:space:]') bytes"

echo "== [4/4] upgrade on mainnet (preserves stable memory: posts + SPA + tokens) =="
dfx canister install "$CANISTER" --network ic --identity pyre-dev \
    --mode upgrade --wasm "$GEN/$CANISTER.wasm" --yes
echo "DONE — pyrepress upgraded with native _pyre_native on mainnet"
