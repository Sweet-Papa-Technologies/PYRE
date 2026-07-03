# PyrePress — backend (Phase A)

A certified, tamper-proof blog backend running inside an Internet Computer
canister, built on [PYRE](https://github.com/Sweet-Papa-Technologies/PYRE)
(`pip install pyre-icp`). Posts are written in Markdown, rendered to HTML
*in the canister*, and each **published post's exact path is a certified
route** — readers can cryptographically verify the bytes against the
network's root of trust.

## Layout

```
src/app.py              routes, auth gate, per-post certified-route logic
src/main.py             Kybra glue (edited: @init/@post_upgrade rebuild
                        the dynamic certified routes before recertify)
src/pyrepress/          config, posts model, renderer, RSS feed, seeds
tests/                  pytest suite (runs on host CPython, no replica)
scripts/smoke.sh        paste-ready curl walk of the whole API
scripts/seed.sh         load demo posts (incl. the PYRE announcement)
```

## Setup

```bash
cd backend
~/.pyenv/versions/3.10.7/bin/python -m venv .venv && source .venv/bin/activate
pip install pyre-icp kybra==0.7.1 pytest
python -m kybra install-dfx-extension     # once, for deploys
```

## Iterate locally (no replica)

```bash
pyre dev src/app.py
BASE=http://127.0.0.1:8000 ./scripts/smoke.sh
```

## Tests

```bash
python -m pytest tests/ -q
```

## Deploy to a local replica / mainnet

```bash
dfx start --background
dfx deploy                                   # venv must be active (Kybra)
BASE="http://$(dfx canister id pyrepress).localhost:4943" ./scripts/smoke.sh

dfx deploy --network ic                      # mainnet (needs cycles)
```

On-chain, certified responses carry an `IC-Certificate` header:

```bash
curl -si "http://$(dfx canister id pyrepress).localhost:4943/api/health" | grep -i ic-certificate
```

## Auth

All writes require `Authorization: Bearer <token>`; reads and
`POST /api/posts/{slug}/view` are public. The dev default token is
`pyrepress-dev-token` (only its sha256 lives in code — see
`src/pyrepress/config.py`). **Rotate it before any real deploy:**

```bash
curl -X PUT -H "Authorization: Bearer pyrepress-dev-token" \
  -d '{"token":"a-new-strong-secret"}' "$BASE/api/meta"
```

## API

| Route | Auth | Certified | Notes |
|---|---|---|---|
| `GET /api/health` | – | yes | liveness |
| `GET /api/meta` | – | yes | blog config |
| `PUT /api/meta` | bearer | – | update config / rotate token |
| `GET /api/posts` | – | yes | canonical first page (query params ignored — certified snapshot) |
| `GET /api/posts/query?limit&after&tag` | – | – | live list, newest-first, cursor pagination |
| `GET /api/posts/{slug}` | – (drafts: bearer) | yes, per published post | includes `verify` block (canister id, path, how-to-verify) |
| `POST /api/posts` | bearer | – | `{title*, markdown*, slug?, tags?, status?}`; 409 on slug collision |
| `PUT /api/posts/{slug}` | bearer | – | partial update; slug rename moves the certified route |
| `DELETE /api/posts/{slug}` | bearer | – | |
| `POST /api/posts/{slug}/view` | – | – | anonymous view counter (stored outside the post doc) |
| `GET /api/feed.xml` | – | yes | RSS 2.0, latest 20 published |
| `POST /api/seed` | bearer | – | idempotent demo content |

### ⚠️ Uncertified reads behind the certifying gateway

The certifying gateway (`<cid>.localhost:4943`, `<cid>.icp0.io`) returns
`503 backend_response_verification` for the **uncertified** GET routes
(`/api/posts/query`, draft previews) once certified paths exist — a PYRE
limitation (the skip-certification witness carries no absence proof for the
request's own path; see the dogfood friction log, item F16). Serve those via
the `raw` subdomain
(`<cid>.raw.localhost:4943`) or filter/paginate client-side from the certified
`GET /api/posts`. Certified routes work on both domains. (`pyre dev` has no
gateway, so `smoke.sh` passes fully there.) Independent verification of a
certified post needs the 4th `connect` arg on macOS:
`verify_certification.py <url> <cid> 127.0.0.1:4943`.

### How per-post certification works

PYRE certifies **static** GET paths only. PyrePress therefore registers each
published post's exact path (`/api/posts/<slug>`) as a certified route at
publish time; PYRE's automatic post-update `recertify()` snapshots it in the
same update call. Unpublish/rename/delete keep the route set in sync, and
`@init`/`@post_upgrade` rebuild the registrations from stable memory (see
`sync_certified_routes()` in `src/app.py`).

## Integration seams (for the SPA/OIDC work)

- `src/app.py` has a marked seam for `pyre.static` SPA mounting — every API
  route lives under `/api/`, so a catch-all cannot collide.
- A second seam marks where Phase B/C comment + OIDC routes land.
- The slug `query` is reserved (`pyrepress.posts.RESERVED_SLUGS`) because
  `/api/posts/query` is a route; reserve any new sub-resource segment there.
