# PYRE — Python Runtime for the Edge

Write recognizable Python — Flask-style routes, a data layer, an outbound
HTTP call — and run it on the [Internet Computer](https://internetcomputer.org)
(ICP), a decentralized WASM host. No Candid, no Rust, no Motoko. Responses
can be **cryptographically certified**: clients verify your API's answers
against the network's root of trust instead of trusting a server.

**Docs:** [quickstart](docs/quickstart.md) · [concepts](docs/concepts.md) ·
[API reference](docs/api.md) · [troubleshooting](docs/troubleshooting.md) ·
[stdlib support matrix](docs/stdlib-matrix.md) ·
reference app: [examples/food_tracker](examples/food_tracker/src/app.py)

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
    return Response.json(items.insert(req.json()), status=201)   # schema-validated

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
(v1.1 — every one opt-in, none required for a CRUD app):

```python
from pyre import random as prandom, time as ptime, sign
from pyre.adapters import supabase

@app.get("/id")
def new_id(req):
    return Response.json({"id": prandom.uuid4()})   # consensus-safe; naive uuid4 warns in dev

@app.get("/attest", update=True)
async def attest(req):
    token = await sign.jwt({"sub": req.caller, "iat": ptime.now()})
    return Response.json({"jwt": token})            # threshold-signed: no private key exists

@app.get("/external", update=True)
async def external(req):
    db = supabase.Client(url=SUPA_URL, anon_key=SUPA_KEY)
    return Response.json(await db.table("items").select().limit(10))
```

## Quick start

From PyPI: `pip install pyre-icp` — the distribution is `pyre-icp`, but the
import package and the CLI are both `pyre`.

Working from a clone of this repo:

```bash
make setup          # venvs (Python 3.10.7 via pyenv), kybra, dfx extension
make test           # unit tests, no replica needed
make dev            # instant local server for examples/rest_api

make start          # dfx start --background --clean
make deploy         # build + deploy the example canisters to the local replica
make e2e            # curl-level acceptance tests (Example A + B)
make determinism    # Phase 1 outcall determinism gate
make budgets        # §5.4 instruction measurements
```

New project: `pyre new myapp` (with `.venv-dev/bin` or the venv on PATH).

## The four ICP concepts PYRE teaches (and hides everything else)

### 1. Query vs. update calls

ICP has two kinds of calls. **Queries** are fast, read-only, and
non-replicated. **Updates** go through consensus (~1–2 s), can write state,
and can make outbound HTTP calls.

PYRE maps this to HTTP conventions: GET routes are queries; POST/PUT/DELETE
routes, `async` handlers, and anything marked `update=True` are updates.
When a browser hits an update route, the canister replies "upgrade" and the
HTTP gateway re-sends the request as an update — you never see it, but
that's why writes are slower than reads.

Honesty guards: writing `pyre.kv` or calling `urlopen` from a query route
raises a typed error (locally in `pyre dev` too) instead of being silently
discarded on-chain.

### 2. Outbound HTTP is async and consensus-gated

Every replica in the subnet performs your outbound HTTPS call
independently, and they must all agree byte-for-byte on the result. This is
why `urlopen` is awaitable and only works in update context. Generator
style (`resp = yield urllib.urlopen(...)`) works too.

### 3. The determinism transform

Upstream responses differ per replica — `Date`, `Set-Cookie`, request IDs,
CDN trace headers. Every outcall therefore runs through a **transform**
that canonicalizes the response before consensus. PYRE's
`default_transform` keeps only `content-type` and `content-encoding`
(lowercased, sorted) and passes the body through untouched. If the *body*
is nondeterministic (timestamps, request IDs in JSON), register your own
transform query in `main.py` and pass its name as `transform=`.

`pyre dev` performs real HTTP and logs exactly which headers the transform
will strip on-chain, so surprises show up before you deploy.

### 4. Interpreter lifecycle & instruction budgets

Canisters are long-lived actors, not per-request lambdas: the Python
interpreter boots once at install/upgrade and stays warm in the heap.
There is no per-request cold start — but `init`/`post_upgrade` and each
message have (large) instruction ceilings. `make budgets` records what the
framework itself costs; the headroom is your app's budget. See
DECISIONS.md for measured numbers.

## What's here

```
pyre/                  the framework (pure Python 3.10; CDK-free except main.py glue)
  application.py routing.py  Flask-style App, hooks, error handlers, query/update mapping
  certification.py     response verification v2 — certified reads (pure Python)
  gateway.py           http_request / http_request_update adapter (dict-level)
  kv.py data.py        stable-memory KV + collections with schema & lazy migration
  auth.py cors.py validation.py   bearer/API-key + Basic auth, CORS, dict-schema 400s
  prandom.py ptime.py puuid.py    consensus-safe randomness/UUIDs/time (v1.1)
  sign.py              threshold tECDSA signing + ES256K JWTs (v1.1)
  log.py               structured logging retrievable via `dfx canister logs` (v1.1)
  adapters/            Supabase + Upstash over outcalls, amplification-aware (v1.1)
  transform.py outcall.py compat/  determinism transform, async pump, urllib shim
  dev.py cli.py        `pyre dev` local runner, `pyre new`, footgun warnings
examples/              rest_api · outbound · phase1_spike · food_tracker · stdlib_audit
tests/                 unit/ (~200 tests, no replica) + pocketic/ (canister-level)
scripts/               e2e, determinism gate, budget/size gates, verifiers, teardown
DECISIONS.md           pinned platform facts + every measured number
```

## Scope fences

Pure Python only — no C extensions, no Pydantic. No sockets/threads (stubbed
with guidance), no websockets/streaming. Secret-bearing outcalls (calling
Stripe/OpenAI with a private key) are a
[documented limitation](docs/secrets-and-outcalls.md) until v1.2's signed
proxy. Mainnet-proven: certification, determinism, and costs are validated
on ICP mainnet (see DECISIONS.md).
