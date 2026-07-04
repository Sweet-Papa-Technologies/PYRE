# Quickstart — running locally in minutes, $0, no wallet

The honest shape of this: **you can build and fully exercise a PYRE app
locally for free, with no blockchain identity, no ICP, and no cycles.** The
only wall is putting a *persistent* canister on mainnet — that needs cycles,
and there's a free-coupon path for it below. So the plan is: get productive
locally first, cross the mainnet wall only when you actually want a public
URL.

## 1. Install the toolchain

```bash
# Python 3.10.7 — Kybra's build interpreter (see "A note on Python 3.10" below)
pyenv install 3.10.7

# dfx (the Internet Computer SDK)
DFXVM_INIT_YES=true sh -c "$(curl -fsSL https://internetcomputer.org/install.sh)"

# a project venv with pyre + kybra
~/.pyenv/versions/3.10.7/bin/python -m venv venv && source venv/bin/activate
pip install pyre-icp kybra==0.7.1
python -m kybra install-dfx-extension
```

## 2. Create and run an app — no blockchain at all

```bash
pyre new myapp --template crud-kv
cd myapp
pyre dev src/app.py
```

```bash
curl -X POST -d '{"name": "apple", "qty": 3}' http://127.0.0.1:8000/items
curl http://127.0.0.1:8000/items
```

`pyre dev` is a plain local server running the same routing code the
canister runs. Outbound calls do real HTTP and log what ICP's determinism
transform would strip. Query/update rules are enforced locally so on-chain
surprises surface now, not after deploy. There is **no auto-reload**:
after editing code, Ctrl-C and rerun (startup is instant).

## 3. Deploy to a local replica — still free, still no wallet

This is a real Internet Computer canister on a local replica. **It costs
nothing** — dfx funds local canisters automatically; there is no identity,
ICP, or cycles step. You get the whole framework here: certified responses,
state, upgrades, outcalls.

```bash
dfx start --background
dfx deploy           # first build compiles the runtime — go get coffee
curl "http://$(dfx canister id myapp).localhost:4943/health"
```

That `/health` response arrives with an `IC-Certificate` header — it is
cryptographically certified, not just served (see concepts.md).

Two things you'll see and can ignore/fix:

- dfx prints a *"dfx is deprecated, use icp-cli"* notice on every command.
  These docs stay on dfx because Kybra's build extension targets it —
  the notice is safe to ignore for now.
- If the replica misbehaves (deploy hangs, `error sending request`,
  "already running" confusion), the universal reset is:
  `dfx killall && dfx start --clean --background` — note `--clean` wipes
  local canister state.

Realistically, **steps 2–3 are 90% of your loop.** Build the whole app
here for free; only go to mainnet when you want a public, persistent URL.

## 4. Deploy to mainnet (the one paid dependency)

First, an honest heads-up so you don't waste an hour: the popular
"zero-setup, click-to-deploy" ICP options **do not work for PYRE.** A Kybra
canister is a ~27 MB uncompressed Wasm (the embedded Python interpreter), and:

- **`dfx deploy --playground`** rejects it — the playground caps uncompressed
  Wasm at 10 MiB and forbids gzip.
- **ICP Ninja** (icp.ninja) is Motoko/Rust-only; Python isn't supported.

So a persistent public URL means a funded mainnet canister. It's not
expensive — a light backend runs for well under $1/month — and there's a
free way to get the initial cycles.

### The free path: a cycles faucet coupon

DFINITY gives developers a free cycles coupon (on the order of 10–20T
cycles — plenty to create and install one PYRE canister):

1. Go to **[faucet.dfinity.org](https://faucet.dfinity.org)** → *Request Cycles*.
2. It routes you through the DFINITY Discord `#cycles-faucet` channel + a
   short survey; a bot DMs you a coupon code. **Set expectations:** this is
   gated and not always instant — coupons are handed out on request, not
   guaranteed self-serve.
3. Redeem and deploy:

```bash
dfx identity new mydev                       # a dedicated key; back up the .pem!
dfx cycles redeem-faucet-coupon <CODE> --network ic --identity mydev
dfx deploy --network ic --identity mydev
curl "https://$(dfx canister id myapp --network ic --identity mydev).icp0.io/health"
```

`dfx deploy` auto-chunks the Wasm (it ships the ~14 MB gzip and the IC
decompresses on install), so the large-Wasm size is handled for you.

### The fallback: buy a little ICP

If you can't get a coupon, fund the identity directly — roughly $2 covers
creating and installing a canister:

```bash
dfx ledger account-id --identity mydev       # send ~1 ICP here from an exchange
dfx cycles convert --amount 0.9 --network ic --identity mydev
dfx deploy --network ic --identity mydev
```

Platform facts worth knowing (details in concepts.md): canister creation
costs 0.5T cycles, and installing the Python runtime needs ~0.4T in the
canister — that's the ~$2. Keep the canister topped up; `dfx canister
status` shows the burn rate.

---

## A note on Python 3.10 (and what actually runs on-chain)

You install **CPython 3.10.7 only as Kybra's build tool** — it runs the
compiler that turns your `.py` files into a WebAssembly module. It is *not*
shipped into the canister and does *not* execute at runtime.

What runs inside the canister is **RustPython** (a Python interpreter
written in Rust) compiled to Wasm, plus Rust crates for the
security-critical primitives (signing, verification, AEAD, hashing come
from the IC system API and audited RustCrypto — not from Python's stdlib).
So:

- **CPython 3.10 reaches end-of-life on 2026-10-31.** That EOL applies to
  the *host build interpreter*, not to a deployed canister — an on-chain
  PYRE app keeps running its frozen RustPython+Rust Wasm regardless. The
  practical follow-up is to keep your **build environment** patched (a
  maintained 3.10 build) or track a future Kybra host-Python bump.
- **Kybra is still Beta** and moves slowly (0.7.1 is the current pin). PYRE
  pins `kybra==0.7.1` deliberately for reproducibility. Treat the toolchain
  as beta-grade; the security load-bearing code (crypto, certification) is
  Rust, and that's what the [security posture](crypto.md) rests on.

This is the truthful framing: PYRE is Python-*authored* and runs on a
Rust-based interpreter — not "a service running on an EOL CPython."
