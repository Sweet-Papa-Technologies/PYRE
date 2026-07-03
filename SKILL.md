---
name: pyre-icp
description: Build, run, and deploy PYRE apps — Flask-flavored Python backends on the Internet Computer (ICP). Use when writing PYRE canister code, debugging Kybra builds, deploying to a local replica or mainnet, or reaching for randomness/crypto/signing/external APIs inside a canister.
---

# Working with PYRE (Python Runtime for the Edge)

PYRE is a Flask-flavored Python framework that runs on ICP canisters via
Kybra 0.7.1 (RustPython 3.10 → WASM). This file is the operational
knowledge an agent needs. It links to the live docs rather than restating
them — **follow the links for current APIs**; trust this file for the
rules and traps.

Live docs root: https://github.com/Sweet-Papa-Technologies/PYRE/tree/main/docs
- API reference: [docs/api.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/api.md)
- Quickstart: [docs/quickstart.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/quickstart.md)
- Concepts (query/update, outcalls, transforms, funding): [docs/concepts.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/concepts.md)
- Troubleshooting (symptom → cause → fix): [docs/troubleshooting.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/troubleshooting.md)
- What stdlib works in-canister: [docs/stdlib-matrix.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/stdlib-matrix.md)
- Platform facts + every measured number: [DECISIONS.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/DECISIONS.md)

## Environment setup (exact versions matter)

```bash
pip install pyre-icp                  # library + `pyre` CLI (import name: pyre)
# Deploying canisters additionally needs:
#   Python 3.10.x  (Kybra's RustPython is 3.10 — use pyenv)
#   dfx:  DFXVM_INIT_YES=true sh -ci "$(curl -fsSL https://internetcomputer.org/install.sh)"
#   In the project's deploy venv: pip install kybra==0.7.1
#                                 python -m kybra install-dfx-extension
```

Two-venv pattern (important): a **lean deploy venv** with only
kybra + pyre-icp (Kybra bundles the whole site-packages into the wasm)
and a separate dev venv for pytest/tooling. Kybra builds require the
deploy venv to be **active**. First build compiles a Rust toolchain
(~20 min); later builds are fast.

## The golden rules (violating these breaks consensus or worse)

1. **Never use stdlib entropy in-canister.** `uuid.uuid4()`, `os.urandom()`,
   `secrets.*` have NO entropy source — pyre defuses them to raise
   `FakeEntropyError`. Use `pyre.random.uuid4()` (ids) or
   `await pyre.random.raw_bytes(n)` (cryptographic, update-only).
   `random.random()`/`datetime.now()` work but are dev-warned;
   timestamps via `pyre.time` == IC consensus time.
2. **Writes and outcalls need update context.** GET routes are queries;
   mark routes `update=True` (or use POST/async) to write `pyre.kv` or
   call `urlopen`. Query-context violations raise typed errors, locally too.
3. **Outcalls fan out ~13×** (one per replica). Every external write must
   be idempotent — client-generated keys + upserts. The adapters
   (`pyre.adapters.supabase/upstash`) enforce this shape; don't bypass
   them with raw POSTs to DBs. GET/HEAD/POST only, ~2s latency.
4. **Outcall responses must be byte-identical across replicas** — always
   use a transform (default strips volatile headers); volatile JSON body
   fields need a custom transform (see examples/phase1_spike).
5. **IPv6 first.** Replicas prefer AAAA; IPv4-only hosts ride an automatic
   platform fallback that works for some providers (verified: Supabase)
   but not all — test your provider from mainnet before depending on it.
6. **Never write plaintext secrets to canister state or logs** — node
   operators can read canister memory. Secret-bearing outcalls (Stripe
   keys etc.) are a documented limitation:
   [docs/secrets-and-outcalls.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/secrets-and-outcalls.md).
   Canister-side `pyre.crypto` encryption does NOT hide data from node
   operators (key lives in canister memory): [docs/crypto.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/crypto.md).
7. **File basenames must not collide** with stdlib/framework/CDK module
   names (Kybra flattens all modules to top-level basenames — a user
   `app.py` is fine, but never create `random.py`, `http.py`, `uuid.py`…).
   `pyre new`/`pyre dev` warn on reserved names.

## Canister project shape

`pyre new myapp --template crud-kv` scaffolds the canonical layout:
`src/app.py` (routes — pure Python, testable anywhere) + `src/main.py`
(Kybra glue: Candid records, `StableBTreeMap` declaration,
`http_request`/`http_request_update`, `pyre_default_transform`,
`@init`/`@post_upgrade` calling `app.recertify()`). Rules baked into the
template that you must preserve if editing `main.py`:
- `@init`/`@post_upgrade` need explicit `-> void` annotations.
- `StableBTreeMap` must be declared statically in `main.py` (Kybra finds
  it by static analysis) and handed to pyre via `pyre.kv.bind_backend()`.
- Candid record names are global and structural — no import aliases, no
  duplicate names across modules.

## Dev loop

```bash
pyre dev src/app.py        # instant local server; real HTTP for outcalls;
                           # prints footgun warnings + transform previews
pytest                     # app logic is plain Python — test it directly
dfx start --background && dfx deploy    # real local replica
dfx deploy --network ic                 # mainnet (funding: see concepts.md)
```

## Debugging Kybra builds (the traps, in order of hours they cost)

- `💣 Kybra error: compilation` with no detail → the real error is hidden;
  run `~/.config/kybra/0.7.1/bin/kybra_generate .kybra/<canister>/py_file_names.csv main /dev/stdout 0.7.1`.
- Renamed/deleted a module and things got weird → `rm -rf .kybra` (stale
  bundle cache mixes old copies in).
- `type X used but never defined` / duplicate-type errors → Candid alias
  limitation; rename records (structural matching makes this safe).
- Old code appears to run after deploy → partial multi-canister deploy;
  check `dfx canister status <c>` module hash against your local build.
- Live logs without redeploying: `dfx canister logs <c> [--network ic]`
  (pyre.log lines land there).

## Capability quick reference (all opt-in; links are authoritative)

- Certified responses: `@app.get(path, certified=True)` — verify with
  `scripts/verify_certification.py` or the official `@dfinity/response-verification`.
- Threshold signing / JWTs: `pyre.sign` — default key `key_1` works on the
  local replica AND mainnet; ~26B cycles/signature; tECDSA only (CDK-gated).
- Randomness/UUIDs/time: `pyre.random`, `pyre.uuid`, `pyre.time` —
  [docs/random-uuid-time.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/random-uuid-time.md).
- Encryption/hashing: `pyre.crypto` (AES-GCM, ChaCha20-Poly1305, blake3
  need the native extension: `scripts/build_native.sh <canister> --install`;
  hashing/HMAC work everywhere).
- External DBs: `pyre.adapters` —
  [docs/adapters.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/adapters.md)
  (read the amplification section before any write path).
- Extending with Rust: [docs/extending-with-rust.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/extending-with-rust.md).

## Costs & operations (mainnet-measured; details in DECISIONS.md)

Queries ~97k cycles (≈free), updates ~27M, outcalls ~100M + 13× upstream
amplification, tECDSA signature ~26.2B, idle ~2.1B/day at ~48MB. Light
backend ≈ $0.40/month. Creating a canister costs 0.5T cycles + ~0.45T for
install (interpreter boot); **every upgrade re-pays interpreter init** —
keep ~0.5T balance headroom. Reclaim cycles before deleting canisters
(withdraw → confirm → delete; `make teardown-mainnet` in the repo does it
safely — deleting an underfunded canister burns its balance).

## Repo development (working on PYRE itself)

`make setup test dev deploy e2e pocketic budget-gate` — CI mirrors these.
Unit tests never need a replica (the kybra seam is mocked). Any new
module: keep CDK contact behind lazy imports (the Basilisk-swap seam),
add unit tests + PocketIC coverage, and pass the size gate (wasm bloat =
idle burn forever). Record platform findings in DECISIONS.md.
