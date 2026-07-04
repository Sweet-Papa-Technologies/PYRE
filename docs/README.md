# PYRE documentation

**PYRE** is Flask-flavored Python that runs on the [Internet Computer](https://internetcomputer.org)
(ICP) as a certified WASM canister — recognizable routes, a data layer, and
outbound HTTP, with no Candid, Rust, or Motoko in your code. You get certified
responses clients can cryptographically verify, threshold-signed JWTs with no
private key to steal, consensus-safe randomness, and a light backend that runs
for roughly **$0.40/month** on mainnet. Install it with `pip install pyre-icp`.
This entire documentation site's demo — **PyrePress** — is itself a PYRE app,
served straight from a canister.

> **Start here → [Quickstart](quickstart.md).** You can build and fully exercise
> a PYRE app locally for free, in minutes, with no blockchain identity, no ICP,
> and no cycles — only a persistent mainnet URL costs anything (there's a free
> cycles-coupon path). One honest caveat up front: **Python 3.10.7 is a *build*
> tool** — Kybra's compiler that turns your `.py` into Wasm. It is not what runs
> on-chain (that's RustPython + audited Rust crates), so CPython 3.10's EOL is a
> build-toolchain note, not a running-service one — see the quickstart's
> [runtime note](quickstart.md#a-note-on-python-310-and-what-actually-runs-on-chain).

## Getting started

| Page | What's in it |
|---|---|
| [Quickstart](quickstart.md) | Install the toolchain, `pyre new`, `pyre dev`, local replica, and the mainnet coupon path — the free local loop in minutes |
| [Concepts](concepts.md) | The mental model: the five ICP concepts PYRE teaches (query vs. update, async outcalls, the determinism transform, long-lived actors) and hides everything else |

## API & data

| Page | What's in it |
|---|---|
| [API reference](api.md) | `App` / `Request` / `Response` routing, `data`/`kv` collections over stable memory, `validate`, `auth`, and `sign` (threshold tECDSA + JWTs) |
| [Static serving](static-serving.md) | `pyre.static` — host a built SPA (Vue/Vite/React `dist/`) from the canister with a certified index and chunked stable-memory assets; `pyre assets push` |
| [Adapters](adapters.md) | `pyre.adapters` — Supabase (PostgREST) and Upstash Redis over outcalls, with amplification-safe writes |

## Security & crypto

| Page | What's in it |
|---|---|
| [Crypto](crypto.md) | `pyre.crypto` — AES-GCM, ChaCha20-Poly1305, sha2/sha3/blake2/blake3, HMAC over audited RustCrypto; threat model first |
| [OIDC](oidc.md) | `pyre.oidc` — verify Google/OIDC RS256/ES256 ID tokens **in-canister** (JWKS cached + determinism-transformed); real sign-in without trusting a server |
| [Secrets & outcalls](secrets-and-outcalls.md) | The documented limitation: secret-bearing external API calls (Stripe/OpenAI with a private key), why they're hard on ICP, and the path forward |

## Platform & runtime

| Page | What's in it |
|---|---|
| [Randomness, UUIDs & time](random-uuid-time.md) | `pyre.random` / `pyre.uuid` / `pyre.time` — consensus-safe entropy; naive stdlib RNG **fails loudly** in-canister by design |
| [Stdlib support matrix](stdlib-matrix.md) | Empirical audit of Python stdlib under Kybra 0.7.1 / RustPython → WASM: what works, what's stubbed, what to avoid |
| [Extending with Rust](extending-with-rust.md) | The pattern for adding compiled Rust capability to a Kybra canister when Python alone won't do |
| [Observability](observability.md) | `pyre.log` structured logging retrievable via `dfx canister logs`, plus seeing into a live canister |

## Help

| Page | What's in it |
|---|---|
| [Troubleshooting](troubleshooting.md) | Symptoms → causes → fixes for the landmines — every one hit for real during PYRE's build |

---

Every load-bearing claim here — response certification (BLS to the NNS root
key), outcall determinism across real replicas, externally verified threshold
signatures, and the ≈ $0.40/month cost — was tested against ICP mainnet and
recorded in the repo's `DECISIONS.md`.

[GitHub](https://github.com/Sweet-Papa-Technologies/PYRE) ·
[PyPI (`pyre-icp`)](https://pypi.org/project/pyre-icp/) ·
[Sweet Papa Technologies](https://sweetpapatechnologies.com)

MIT © Sweet Papa Technologies
