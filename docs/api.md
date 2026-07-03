# API reference

## App

```python
from pyre import App
app = App(debug=False)          # debug=True adds tracebacks to 500 bodies
```

| Member | Notes |
|---|---|
| `@app.get(path, update=None, certified=False)` | GET route. `certified=True` → snapshot-certified (GET, static path, 2xx only). |
| `@app.post/put/delete(path, update=None)` | Update-context by default. |
| `@app.route(path, methods=(...), update=None)` | Multi-method registration. |
| `@app.before_request` | `fn(request)` → `None` to continue, or a response to short-circuit. |
| `@app.after_request` | `fn(request, response)` → must return the response. Runs at certification time for certified routes. |
| `@app.errorhandler(status)` | Custom body for framework 400/404/405/500. `fn(request, info_dict)`. |
| `app.enable_cors(origins="*", headers=..., expose_headers=..., max_age=..., allow_credentials=False)` | CORS + automatic preflight OPTIONS. |
| `app.recertify()` | Re-render certified snapshots + commit the tree root. Called automatically after updates; call from `@init`/`@post_upgrade` (the template does). |

Path params: `"/items/{id}"` → `req.path_params["id"]`.
Handlers may return a `Response`, `dict`/`list` (→ JSON), `str` (→ text), or `bytes`.

## Request / Response

```python
req.method  req.path  req.headers  req.query  req.query_list  req.body
req.json()          # parsed body; invalid JSON → 400 automatically
req.path_params     # from {param} segments
req.caller          # caller principal string on-chain, None in dev

Response.json(obj, status=200, headers=None)
Response.text(s, status=200)
Response(body, status=200, headers=[...], content_type=None)
```

## pyre.kv — stable-memory KV

```python
kv.set(key, value)   # JSON-serializable values; update context only
kv.get(key, default=None)
kv.delete(key)       # → bool
kv.keys()
```

Survives upgrades. Dev mode warns if a key/field name looks like a secret.

## pyre.data — collections over kv

```python
foods = data.collection("foods",
    schema={"name": str, "kcal": int, "note": (str, "")},   # (type, default) = optional
    version=1, migrate=None)

foods.insert(doc)         # validates, assigns doc["id"], returns doc
foods.get(id, default=None)
foods.replace(id, doc)    # full replace; KeyError if missing
foods.update(id, partial) # merge; KeyError if missing
foods.delete(id)          # → bool
foods.list(limit=20, after=cursor, where={"field": value})
                          # → {"items": [...], "next": cursor|None}
foods.count(); foods.ids()
```

Schema evolution: bump `version=` and supply `migrate=lambda doc, from_v: {...}`;
records migrate lazily on read and persist on next write.

## pyre.validate

```python
from pyre import validate, ValidationError

clean = validate(req.json(), {
    "id": str, "qty": int,          # required
    "note": (str, ""),              # optional with default
    "tags": [str],                  # typed list
    "meta": {"unit": str},          # nested object
})
# bad input raises ValidationError → automatic 400 listing every field
```

## pyre.auth

```python
app.before_request(auth.require_token(
    valid={"token-1"} | callable(token) -> bool,
    header="authorization", scheme="Bearer",    # or header="x-api-key", scheme=None
    exempt=("/health",)))
```

401 with `www-authenticate` on failure; OPTIONS preflights pass through.
Store token **hashes** in state, never tokens (see module docstring).

```python
import hashlib

app.before_request(auth.require_basic(
    users={"alice": hashlib.sha256(b"s3cret").hexdigest()},
    # or a callable: users=lambda username, password: bool
    realm="pyre",                               # WWW-Authenticate realm
    exempt=("/health",)))
```

HTTP Basic (RFC 7617): parses `Authorization: Basic <base64(user:pass)>`,
UTF-8 credentials, constant-time comparison. 401 carries
`WWW-Authenticate: Basic realm="<realm>"`; OPTIONS preflights pass through.
On success the username is available as `req.user`. Store password
**hashes** in the dict (sha256 hexdigest), same guardrail as tokens.

Note: auth protects your *inbound* routes. For calling third-party APIs
that need a secret key (Stripe/OpenAI), see
[secrets-and-outcalls.md](secrets-and-outcalls.md) — a documented
limitation in v1.1.

## pyre.compat.urllib_request — outbound HTTPS

```python
from pyre.compat import urllib_request as urllib

@app.get("/quote", update=True)
async def quote(req):
    resp = await urllib.urlopen("https://api.example.com/x",
        method="GET",                    # GET/HEAD/POST only (platform)
        data=None, headers=None,
        transform=urllib.default_transform,   # or your transform's name, or None
        max_response_bytes=16_384,       # bytes cost cycles
        cycles=None,                     # default 3B; excess refunded
        raise_for_status=False)
    resp.status  resp.headers  resp.read()  resp.json()  resp.text()
```

Generator style works too: `resp = yield urllib.urlopen(...)`.
Typed errors: `OutcallFailed` (with IPv6 hint when it smells like DNS),
`ResponseTooLarge`, `OutcallInQueryContext`, `UpstreamHTTPError`.

## pyre.random / pyre.uuid / pyre.time — consensus-safe entropy & clocks

See [random-uuid-time.md](random-uuid-time.md). Naive `random`, `uuid4`,
`datetime.now`, `os.urandom`, and `secrets` are consensus footguns (or
constant stubs) in-canister; `pyre dev` warns when it sees them.

## pyre.sign — threshold signing (tECDSA)

```python
from pyre import sign

sign.configure(key_name="test_key_1")   # default "key_1" works locally AND on mainnet

@app.get("/attest", update=True)
async def attest(req):
    token = await sign.jwt({"sub": req.caller, "iat": ptime.now()})
    return Response.json({"jwt": token})          # alg ES256K, no key to steal
```

- `await sign.sign(message)` → 64-byte secp256k1 signature (r‖s) over
  sha256(message); `sign.sign_digest(digest32)` for precomputed digests.
- `await sign.public_key()` → 33-byte SEC1 compressed key; verify anywhere:
  `python scripts/verify_signature.py jwt <token> <pubkey-hex>`.
- `derivation_path=("users", user_id)` gives each purpose its own key.
- Costs ~26B cycles per signature on mainnet (attached automatically,
  excess refunded). Update-only, like all system calls.
- Kybra 0.7.1 exposes tECDSA only; threshold **Schnorr lands when the CDK
  does**. This module is the keystone for v1.2's `secure_outcall` proxy.

## pyre.log — retrievable canister logging

```python
from pyre import log
log.info("item created", id=item_id)     # debug/info/warning/error(+fields)
log.exception("sync failed", exc, url=url)
log.set_level("warning")                  # gate emission
```

Retrieve from a live canister: `dfx canister logs <name> [--network ic]`.
Rolling buffer — diagnostics, not an audit trail. Never log secrets.
See [observability.md](observability.md).

## pyre.adapters — external HTTPS databases

Supabase (PostgREST) client and Upstash Redis client over outcalls, with
idempotent-write shapes that survive the ~13× outcall fan-out. Read
[adapters.md](adapters.md) before using — the amplification section is
load-bearing. Integration, not hot path: your primary datastore is
`pyre.data`.
