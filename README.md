<p align="center">
  <img src="https://raw.githubusercontent.com/Sweet-Papa-Technologies/PYRE/main/img/pyre-larger-banner.jpg" alt="PYRE — Python on the Internet Computer" width="720">
</p>

<p align="center">
  <a href="https://pypi.org/project/pyre-icp/"><img src="https://img.shields.io/pypi/v/pyre-icp?color=e05d44&label=pypi%20%7C%20pyre-icp" alt="PyPI"></a>
  <a href="https://github.com/Sweet-Papa-Technologies/PYRE/actions/workflows/ci.yml"><img src="https://github.com/Sweet-Papa-Technologies/PYRE/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <img src="https://img.shields.io/badge/python-3.10-blue" alt="Python 3.10">
</p>

Write recognizable Python — Flask-style routes, a data layer, an outbound
HTTP call — and run it on the [Internet Computer](https://internetcomputer.org)
(ICP), a decentralized WASM host. No Candid, no Rust, no Motoko.

What that buys you over Flask-on-a-VPS:

- **Certified responses** — clients cryptographically verify your API's
  answers against the network's root of trust, not "trust the server."
- **Threshold-signed JWTs** — the subnet signs cooperatively; there is no
  private key anywhere to steal.
- **Consensus-safe randomness & audited encryption** — the platform
  footguns are defused; the safe paths look like ordinary Python.
- **~$0.40/month** for a light backend, measured on mainnet.

```python
from pyre import App, Request, Response, data

app = App()
app.enable_cors(origins="*")

items = data.collection("items", schema={"name": str, "qty": (int, 1)})

@app.get("/health", certified=True)     # served with a verifiable certificate
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})

@app.post("/items")                     # runs as an update: writes persist
def create_item(req: Request) -> Response:
    return Response.json(items.insert(req.json()), status=201)

@app.get("/items")
def list_items(req: Request) -> Response:
    return Response.json(items.list(limit=20, after=req.query.get("after")))
```

Outbound HTTPS looks like urllib, but async — because on ICP it is:

```python
from pyre.compat import urllib_request as urllib

@app.get("/quote", update=True)
async def quote(req):
    resp = await urllib.urlopen("https://api.example.com/quote",
                                max_response_bytes=8_192)
    return Response.json({"upstream_status": resp.status, "data": resp.json()})
```

And ICP's genuinely differentiated capabilities read like ordinary Python
(every one opt-in — a plain CRUD app never meets them):

```python
from pyre import random as prandom, time as ptime, sign
from pyre.adapters import supabase

@app.get("/id")
def new_id(req):
    return Response.json({"id": prandom.uuid4()})   # consensus-safe; naive uuid4 fails loudly

@app.get("/attest", update=True)
async def attest(req):
    token = await sign.jwt({"sub": req.caller, "iat": ptime.now()})
    return Response.json({"jwt": token})            # threshold-signed: no key to steal

@app.get("/external", update=True)
async def external(req):
    db = supabase.Client(url=SUPA_URL, anon_key=SUPA_KEY)
    return Response.json(await db.table("items").select().limit(10))
```

## Install

```bash
pip install pyre-icp
```

The distribution is `pyre-icp`; the import package and the CLI are both
`pyre`. To deploy canisters you also need, one time:

- **Python 3.10.x** (Kybra's RustPython targets 3.10 — [pyenv](https://github.com/pyenv/pyenv) recommended)
- **dfx** (the ICP SDK): `DFXVM_INIT_YES=true sh -ci "$(curl -fsSL https://internetcomputer.org/install.sh)"`
- **Kybra** in your project's deploy venv: `pip install kybra==0.7.1` +
  `python -m kybra install-dfx-extension`

Then:

```bash
pyre new myapp --template crud-kv     # bare-api | crud-kv | outbound-proxy
cd myapp
pyre dev src/app.py                   # instant local server, no replica needed
dfx start --background && dfx deploy  # real local canister
dfx deploy --network ic               # mainnet
```

The [quickstart](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/quickstart.md)
walks the whole path in ~15 minutes.

## The API surface

| Module | What it gives you | Docs |
|---|---|---|
| `pyre.App` / `Request` / `Response` | Flask-style routing, path params, hooks, error handlers, CORS, certified routes | [api.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/api.md) |
| `pyre.data` / `pyre.kv` | Collections + KV over stable memory — survives upgrades; schemas, pagination, lazy migration | [api.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/api.md#pyredata--collections-over-kv) |
| `pyre.validate` | Dict-schema request validation → clean per-field 400s | [api.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/api.md#pyrevalidate) |
| `pyre.auth` | Bearer / API-key / HTTP Basic middleware, constant-time, hash-stored creds | [api.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/api.md#pyreauth) |
| `pyre.compat.urllib_request` | urllib-shaped async HTTPS outcalls with determinism transforms | [concepts.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/concepts.md) |
| `pyre.random` / `pyre.uuid` / `pyre.time` | Consensus-safe RNG, UUIDs, timestamps (naive stdlib entropy **fails loudly** in-canister — by design) | [random-uuid-time.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/random-uuid-time.md) |
| `pyre.crypto` | AES-GCM, ChaCha20-Poly1305, sha2/sha3/blake2/blake3, HMAC — audited RustCrypto under the hood | [crypto.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/crypto.md) |
| `pyre.sign` | Threshold tECDSA signatures + ES256K JWTs — no private key exists | [api.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/api.md#pyresign--threshold-signing-tecdsa) |
| `pyre.adapters` | Supabase (PostgREST) + Upstash Redis over outcalls, amplification-safe writes | [adapters.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/adapters.md) |
| `pyre.log` | Structured logging retrievable via `dfx canister logs` | [observability.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/observability.md) |
| `pyre` CLI | `pyre new` (templates), `pyre dev` (local server + footgun warnings) | [quickstart.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/quickstart.md) |

**All docs:**
[quickstart](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/quickstart.md) ·
[concepts](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/concepts.md) ·
[API reference](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/api.md) ·
[troubleshooting](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/troubleshooting.md) ·
[stdlib support matrix](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/stdlib-matrix.md) ·
[secrets & outcalls](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/secrets-and-outcalls.md) ·
[extending with Rust](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/extending-with-rust.md) ·
[observability](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/observability.md) ·
[LLM/agent skill file](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/SKILL.md) ·
reference app: [examples/food_tracker](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/examples/food_tracker/src/app.py)

## The four ICP concepts PYRE teaches (and hides everything else)

1. **Query vs. update calls.** Queries are fast, read-only, uncertified;
   updates go through consensus (~1–2 s) and can write. PYRE maps GET →
   query, writes/async → update; honesty guards raise if you write state
   or make outcalls from a query.
2. **Outbound HTTP is async and consensus-gated.** Every replica performs
   your outcall independently and must agree byte-for-byte — hence
   `await`, and hence transforms.
3. **The determinism transform.** Upstream responses differ per replica
   (Date headers, request ids). Outcalls run through a transform that
   canonicalizes the response before consensus; `pyre dev` shows you what
   gets stripped before you ever deploy.
4. **Canisters are long-lived actors.** The interpreter boots once at
   install and stays warm — no cold starts, but funding (cycles) and
   instruction budgets are real. `make budgets` measures; DECISIONS.md
   records.

Full explanations with failure symptoms in
[concepts.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/concepts.md).

## Mainnet-proven, not aspirational

Every load-bearing claim was tested against ICP mainnet (13-node subnet)
and recorded in
[DECISIONS.md](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/DECISIONS.md):
response certification verified by the official DFINITY verifier (BLS to
the NNS root key, tamper/stale rejected), outcall determinism proven
across real replicas, threshold signatures externally verified
(26.19B cycles ≈ 3.5¢ each), 13× write-amplification converging to single
rows through the adapters, and a light backend costing ≈ $0.40/month.

## Working from a clone

```bash
make setup          # venvs (Python 3.10.7 via pyenv), kybra, dfx extension
make test           # ~240 unit tests, no replica needed
make dev            # instant local server for examples/rest_api
make start deploy   # local replica + all example canisters
make e2e            # 20-check acceptance suite
make pocketic       # canister-level integration tests
make budget-gate    # instruction + wasm-size/idle-burn regression gates
```

CI runs the same gates on every push. See
[CONTRIBUTING](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/CONTRIBUTING.md).

## Scope fences

Pure Python only — no C extensions, no Pydantic. No sockets/threads
(stubbed with guidance), no websockets/streaming. Secret-bearing outcalls
(calling Stripe/OpenAI with a private key) are a
[documented limitation](https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/secrets-and-outcalls.md)
until v1.2's signed proxy.

## License

MIT © Sweet Papa Technologies
