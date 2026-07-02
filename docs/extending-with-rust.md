# Extending PYRE with Rust — the pattern

v1.1 proved you can add compiled capability to a Kybra canister without
forking the CDK or touching interpreter internals. This page is the
repeatable recipe, worked from the real example: `_pyre_native`, the AEAD
module behind `pyre.crypto`.

## First: do you actually need Rust?

Two kinds of extension, very different cost — label yours before writing
anything:

- **Kind A — wrap an ICP system API Kybra already exposes.** Randomness
  (`raw_rand`), time, threshold signing, timers, outcalls. Pure Python,
  cheap: subclass the outcall future protocol (see `pyre/sign.py`,
  `pyre/prandom.py` — `_to_kybra_call()` + `_process_call_result()` +
  `_resolve_dev()`) and you ride the existing async pump. **Most
  capability work is Kind A.**
- **Kind B — new compiled capability RustPython lacks.** Real Rust at the
  embedding layer. Only three admissible justifications (ROADMAP §3):
  footgun-safety, a genuine capability gap (check
  [the stdlib matrix](stdlib-matrix.md) first — the audit exists so you
  don't guess), or *measured* hot-path pain. "Rewrite in Rust because
  Rust" is a rejected reason. Crypto primitives additionally must wrap
  audited crates (RustCrypto) — never hand-rolled.

## The seam (why this works)

Kybra's build regenerates `.kybra/<canister>/` on every build: it writes a
Cargo project, generates `src/lib.rs`, and runs cargo. The generated
`lib.rs` constructs the RustPython VM in **two** places — `#[init]` and
`#[post_upgrade]` — and the VM exposes `add_native_module()` publicly.
RustPython's `#[pymodule]` macro emits absolute paths, so a module source
file dropped into the generated crate compiles unmodified.

So a post-generate patch of exactly three edits suffices:

1. copy your `.rs` file into `.kybra/<c>/src/`
2. inject your pinned `[dependencies]` lines right after the
   `[dependencies]` header (never append — the file ends with
   `[patch.crates-io]`)
3. add `mod your_module;` plus one `vm.add_native_module(...)`
   registration line after **both** `add_native_modules(...)` calls
   (miss `#[post_upgrade]` and your module vanishes on the first upgrade)

`scripts/build_native.sh` automates the whole cycle — normal build →
patch → warm cargo re-run (~5–8 s) → wasi2ic → the wasm lands where dfx
expects it — and *asserts exactly two registration points*, refusing to
patch if a Kybra upgrade ever changes the generated shape. That assert is
the safety net that makes patching a generated project defensible.

## The worked example

- Rust side: `pyre_native/src/pyre_native.rs` — a `#[pymodule]` exposing
  `aes_gcm_seal/open`, `chacha20poly1305_seal/open`, `blake3`,
  `blake2b_var`. Thin: bytes in, bytes out, error → Python exception.
  Misuse resistance lives in the Python layer (`pyre/crypto.py`), not here.
- Pins: `pyre_native/Cargo.toml` — exact versions (`=0.10.3` style),
  `default-features = false`, and **getrandom disabled everywhere**: a
  canister has no ambient entropy, and a crate that silently pulls it in
  would trap (or worse, stub) at runtime.
- Python side dispatches lazily: `import _pyre_native` in-canister, a
  dev-only pip shim on the host, and a clear `CryptoUnavailable` error
  telling the user to build with `scripts/build_native.sh --install`
  otherwise.

## The discipline (non-negotiable)

1. **Measure size before/after** (`scripts/size_gate.sh`): raw and gzip.
   `_pyre_native` with four crates costs +70,667 raw / +26,518 gz —
   +0.26% of the canister. If your crate costs megabytes, that's idle-burn
   forever on every canister that ships it; justify it or cut features.
2. **Record the numbers in DECISIONS.md** — crate, version, size delta,
   why it's admissible.
3. **Prove both registration points**: deploy, exercise, upgrade twice,
   exercise again (`examples/crypto_demo` shows the shape).
4. **Known-answer tests in-canister**, not just on the host — RustPython's
   native modules have real deviations (its `blake2b` rejects
   `digest_size`; we found out live).
5. Dev-mode parity via a host shim so `pyre dev` and unit tests exercise
   the same Python surface without a replica.

## Limits

- This is a *build-time* patch of generated code pinned to Kybra 0.7.1.
  A CDK bump means re-verifying the seam (the script's asserts catch
  drift loudly).
- Rust extends **capability, not confidentiality**: your Rust runs in the
  same canister memory Python does — node operators see both. Secrets
  stay out of canisters regardless of language
  ([secrets-and-outcalls](secrets-and-outcalls.md)).
