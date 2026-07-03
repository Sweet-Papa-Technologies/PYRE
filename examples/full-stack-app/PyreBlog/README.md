# PyrePress — integrated full-stack certified blog on PYRE

One PYRE/Internet-Computer canister that serves **both** the Vue 3 SPA (at `/`)
**and** the backend API (under `/api/*`), same-origin. Certified reads a reader
can independently verify, Google-OIDC-ready authenticated comments with author
moderation, and the SPA hosted from the same canister — no external CDN or asset
canister.

- `backend/` — the PYRE canister (Flask-flavored Python on Kybra). `src/app.py`
  (routes), `src/main.py` (Kybra glue), `src/pyrepress/` (posts, comments,
  sessions, renderer, feed, config, seeds).
- `frontend/` — Vue 3 + Vite + PrimeVue SPA. Builds to `dist/`, uploaded into the
  canister's stable memory and served by `pyre.static`.

See `SPEC.PyreBlog.md` for the product spec and `API.md` for the wire contract.

---

## Architecture at a glance

```
                 ┌──────────────────────── one canister ────────────────────────┐
  browser  ─────▶│  GET /                    → pyre.static  (certified SPA index) │
  (same    ─────▶│  GET /assets/<hashed>     → pyre.static  (asset catch-all)     │
   origin) ─────▶│  GET /post/<slug> (deep)  → pyre.static  (SPA fallback→index)  │
           ─────▶│  GET /api/posts, /api/... → app.py routes (certified + F16)    │
           └──────────────────────────────────────────────────────────────────────┘
```

API routes always win: `pyre.static`'s catch-all matches at strictly lower
priority than every other route, and all API routes live under `/api/*`, so the
SPA catch-all can never shadow them.

---

## Contract reconciliation (frontend ↔ backend)

The frontend calls **root-relative** paths (`/posts`, `/auth/login`, …); the
backend serves everything under **`/api/*`**. Three seams bridge them:

1. **API prefix** — `frontend/.env.production` sets `VITE_API_BASE=/api`, which
   the API client prepends to every path (`/posts` → `/api/posts`). The dev
   build (`.env.development`) keeps it empty for `pyre dev` same-origin.
2. **Post detail is JSON, not HTML** — the backend serves `GET /api/posts/{slug}`
   as **certified JSON** (`{post, verify}`; see `API.md`). `frontend/src/api/
   client.ts` `getPost()` consumes that JSON (it previously parsed an HTML page
   that the backend never produced) and keeps the response's `IC-Certificate`
   header for the verify panel.
3. **Absolute asset base** — `frontend/vite.config.ts` uses `base: '/'` (not
   `'./'`). A hard load of a deep link like `/post/<slug>` serves `index.html`
   via the SPA fallback; relative `./assets/…` there would resolve against
   `/post/` and 404. Absolute `/assets/…` resolves at every route depth.

Three backend routes were added to match the SPA's author surface
(`backend/src/app.py`): `GET /api/admin/posts`, `GET /api/admin/posts/{slug}`,
`POST /api/posts/{slug}/publish`.

---

## F16 workaround (certifying gateway vs uncertified 2xx GET queries)

Once any certified route exists, the **normal (non-raw)** gateway **503s**
uncertified 2xx GET *query* responses (they verify against the certification
tree and fail). PYRE's fix: mark such a route `update=True` so it is served as a
**consensus-certified update** (works through the normal gateway; ~2s, fine for
non-hot paths). Applied to:

- API reads: `/api/posts/query`, `/api/comments/pending`,
  `/api/moderation/comments`, `/api/admin/posts`, `/api/admin/posts/{slug}`.
- The **static asset catch-all** — `pyre.static.mount` registers it as a query;
  `app.py` re-flags it `update=True` after mount (assets + SPA deep-link
  fallback would otherwise 503 on the normal gateway). See the FRAMEWORK NOTE in
  `app.py`.

The certified fast-read routes (`/api/posts`, `/api/posts/{slug}`,
`/api/feed.xml`, `/api/posts/{slug}/comments`) and the certified SPA index (`/`)
stay query-fast and carry `IC-Certificate`.

---

## Build, deploy, upload

Prereqs: `dfx` (local replica running: `dfx start`), Node ≥ 18, the backend
deploy venv at `backend/.venv` with a **real** (non-editable) install of the
local PYRE checkout and Kybra 0.7.1.

```bash
# (one-time) deploy venv: real install of local pyre (editable traps the Kybra freezer)
backend/.venv/bin/pip install --force-reinstall --no-deps /path/to/PYRE

# 1. build the SPA (base '/', VITE_API_BASE=/api baked in)
cd frontend && npm install && npm run build            # → dist/, index.html refs /assets/…
cd ..

# 2. deploy the backend canister (from backend/dfx.json)
cd backend
source .venv/bin/activate          # so `python -m kybra` uses the deploy venv
dfx deploy pyrepress               # ~20s; upgrades in place, stable data survives
cd ..

# 3. upload the SPA into the canister
CID=$(python3 -c 'import json;print(json.load(open("backend/.dfx/local/canister_ids.json"))["pyrepress"]["local"])')
pyre assets push frontend/dist \
  --url "http://$CID.localhost:4943" \
  --token pyrepress-deploy-token          # = config.STATIC_UPLOAD_TOKEN
```

Open `http://$CID.localhost:4943/` in a browser.

### macOS note: `pyre assets push` and `*.localhost`

Python's resolver can't resolve `<canister-id>.localhost` (curl/Chromium can).
If the push fails with `nodename nor servname provided`, run it through a tiny
shim that maps `*.localhost` → `127.0.0.1` while preserving the `Host` header so
the gateway still routes to the canister:

```python
# push_shim.py
import socket, sys
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, *a, **k: _orig(
    "127.0.0.1" if isinstance(h, str) and h.endswith(".localhost") else h, *a, **k)
from pyre.cli import main
sys.argv = ["pyre", "assets", "push", sys.argv[1], "--url", sys.argv[2], "--token", sys.argv[3]]
sys.exit(main())
```
```bash
python push_shim.py frontend/dist "http://$CID.localhost:4943" pyrepress-deploy-token
```
(A `--connect host:port` option on `pyre assets push`, like
`scripts/verify_certification.py` already has, would remove the need for this.)

---

## Prove it — local end-to-end

```bash
CID=<canister-id> ./scripts/e2e_integrated.sh
```

Exercises, through the **normal** gateway: SPA served + deep-link fallback,
hashed JS asset content-type, certified `/api/posts` + `/api/posts/{slug}`
(with `IC-Certificate`), view counter, RSS, the author loop (admin list incl.
drafts, publish), and the comments loop (unauth→401, login→session,
submit→pending, moderate→certified approved list).

Independent certification verification (replica root key, direct connect):

```bash
backend/.venv/bin/python /path/to/PYRE/scripts/verify_certification.py \
  "http://$CID.localhost:4943/api/posts/<slug>" "$CID" 127.0.0.1:4943
# and the certified SPA index:
backend/.venv/bin/python /path/to/PYRE/scripts/verify_certification.py \
  "http://$CID.localhost:4943/" "$CID" 127.0.0.1:4943
```

---

## Auth (OIDC) — real vs local

- **Real Google OIDC**: set the public client id both in the backend
  (`PUT /api/meta {"google_client_id": "…apps.googleusercontent.com"}`) and the
  frontend (`VITE_GOOGLE_CLIENT_ID`). In-canister RS256/ES256 verification needs
  the `_pyre_native` crypto ext compiled into the canister — see
  `examples/oidc_spike` (the Phase-B gate, proven natively) and `build_native.sh`.
- **Local e2e (OIDC mocked)**: a gated **`dev`** login provider mints a session
  from a plaintext token with **no** signature check. It is enabled **only** when
  the `auth:dev_login` kv flag is set (`PUT /api/meta {"dev_login": true}`,
  bearer-gated) and is **OFF by default** — a default/mainnet deploy can never
  mint dev sessions. `e2e_integrated.sh` enables it, runs the loop, and disables
  it again. **Never enable it on mainnet.**

---

## Tokens / config (change before mainnet)

`backend/src/pyrepress/config.py`:

| Constant / kv key | Purpose | Default (dev) |
|---|---|---|
| `DEFAULT_TOKEN` | author bearer token (writes, moderation) | `pyrepress-dev-token` |
| `STATIC_UPLOAD_TOKEN` | deploy token for `pyre assets push` | `pyrepress-deploy-token` |
| `auth:dev_login` (kv) | local mocked-login gate | unset (off) |
| `auth:google_client_id` (kv) | Google OIDC audience | unset |

Rotate the author token at runtime with `PUT /api/meta {"token": "<secret>"}`
(only its sha256 is stored).
