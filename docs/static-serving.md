# Serving a static frontend (SPA) — `pyre.static`

PYRE can host a built single-page app (Vue/Vite/React `dist/`) **directly
from the canister**: the backend API and the frontend that consumes it ship
as one canister, no external CDN or asset canister needed.

```python
# app.py
from pyre import App, Request, Response, static

app = App()

@app.get("/api/health")
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})

static.mount(app)                      # serve the uploaded dist/ at "/"
static.admin_routes(app, "my-deploy-token")   # authenticated upload API
```

API routes always win: the static catch-all matches at **lower priority
than every other route**, regardless of registration order.

## 1. Build and push

```bash
npm run build                                   # → dist/

# against `pyre dev`
pyre assets push dist/ --url http://127.0.0.1:8000 --token my-deploy-token

# against a local replica / mainnet (same command, different URL)
pyre assets push dist/ --url http://<canister-id>.localhost:4943 --token ...
pyre assets push dist/ --url https://<canister-id>.icp0.io --token ...
```

The pusher walks `dist/`, gzips compressible files (`.js`, `.css`, `.html`,
`.svg`, `.json`, `.wasm`, …) when that helps, skips files whose sha256 the
canister already has, uploads in ≤45 KB chunks with retries, and finalizes
atomically. Configure your bundler for absolute asset URLs (Vite's default
`base: '/'`).

## 2. Serving behavior

`static.mount(app, prefix="/", index="index.html", spa=True,
certified_index=False)` registers:

- `GET <prefix>` — the index route (skipped if you already route that path)
- `GET <prefix>{path:path}` — the asset catch-all

For a `GET`:

1. **Exact asset match** → served with the right `content-type`.
2. **Miss, `spa=True`, no dot in the last path segment, `Accept` includes
   `text/html`** → `index.html` with status 200, so client-side routing
   survives refresh/deep links.
3. **Anything else** → real 404 (PYRE upgrades non-2xx queries and serves
   them consensus-certified via the update path).

Cache headers:

| Path | `cache-control` |
|---|---|
| content-hashed names (`assets/index-Dk7fmR6Y.js`) | `public, max-age=31536000, immutable` |
| `.html` / the index | `no-cache` |
| everything else | `public, max-age=3600` |

The "hashed" heuristic is a `[-.]`-separated 8+ char suffix containing a
digit — rename files that false-positive.

### gzip

Both raw and gzipped bytes are stored (when the pusher provides them); the
served variant follows the request's `Accept-Encoding`, with
`content-encoding: gzip` and `vary: accept-encoding`. Gzip **de**compression
never happens in-canister — we serve exactly what was uploaded.

### Certification

Asset routes are uncertified queries riding the skip-certification
wildcard: cheap, fast, and the standard PYRE trust model for dynamic 2xx
GETs. Pass `certified_index=True` to snapshot the index into the v2
certification tree — the SPA **entry point** becomes tamper-proof, and
because uploads are update calls, the gateway re-certifies automatically
the moment `finalize` swaps a new `index.html` in. Two consequences:

- the certified index always serves the **raw** variant (a certified
  snapshot hashes exact bytes; it cannot vary per `Accept-Encoding`);
- before the first upload the index route serves a 200 placeholder page,
  so `init`/`post_upgrade` re-certification cannot trap.

Note: once a GET catch-all is mounted, a `POST` to an unknown path yields
405 (`allow: GET`) instead of 404 — the path now "exists" for GET.

## 3. Upload protocol (what the CLI speaks)

All endpoints live under `/_pyre/static` (configurable) and require
`Authorization: Bearer <token>`. `token_check` accepts a string, a
container of strings, or a `callable(token) -> bool` (store token *hashes*
in kv for anything beyond a deploy-time secret — canister state is readable
by node providers).

| Endpoint | Body → Result |
|---|---|
| `POST /manifest` | `{"assets": {path: {size, sha256[, content_type, gzip_size, gzip_sha256]}}}` → `{chunk_size, accepted: {path: {chunks, gzip_chunks}}, rejected: {path: reason}}` |
| `POST /chunk` | `{path, index, data: <base64>, variant: "raw"\|"gzip"}` → `{ok: true}` |
| `POST /finalize` | `{paths: [..]}` (or `{}` for all staged) → `{finalized, skipped, errors}` |
| `POST /delete` | `{paths: [..]}` → `{deleted}` |
| `GET /list` | → `{assets: {path: {size, sha256, gzip, gzip_sha256, content_type}}, chunk_size}` |

Semantics:

- Chunks are staged under separate keys; the **live asset keeps serving**
  until `finalize` verifies each variant's sha256 and swaps meta+chunks in
  one update call (one atomic ICP state transition).
- Every chunk except the last must be exactly `chunk_size` (45 000) raw
  bytes, base64-encoded. Re-sending a chunk is a no-op (retry-safe).
- sha256 mismatch → that path errors, staging is kept (re-send the bad
  chunks, finalize again), the live asset is untouched.
- Re-finalizing an already-finalized path reports it under `skipped`.

## 4. Limits

| Limit | Value | Why |
|---|---|---|
| max asset size | 1 800 000 bytes | responses must stay under the ~2 MB gateway cap (headers + certificate share it) |
| chunk size (raw) | 45 000 bytes | 60 000 base64 chars → ≤64 000-byte kv value |
| asset paths | relative; no `..`, empty segments, `:`, `\` | kv key hygiene + traversal safety |

Assets persist in stable memory (they ride `pyre.kv`'s StableBTreeMap) and
survive upgrades. In `pyre dev`, the in-memory kv backend means assets last
for one dev-server process — push after each restart, or seed with
`static.put_asset()` in dev-only code.

## Storage layout (for the curious)

```
static:<path>:meta      {size, sha256, content_type, chunks, gzip, gzip_size, gzip_sha256, gzip_chunks}
static:<path>:c:<n>     base64 of raw slice n
static:<path>:gz:<n>    base64 of gzip slice n
staticup:<path>:...     the same shape, staged during an upload
```

Chunks are base64 because its expansion is a fixed 4/3 and the JSON string
stays pure ASCII on every interpreter; latin-1 passthrough escapes
data-dependently under `json.dumps` (up to 6× for control bytes) and can't
be budgeted against the kv value cap.
