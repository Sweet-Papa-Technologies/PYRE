# PyrePress API contract (Phase A)

The backend is a PYRE canister. Every route below is under `/api/` so a
static-SPA catch-all can be mounted at `/` later without colliding.

- **Base URL (local):** `http://<canister-id>.localhost:4943`
- **Base URL (mainnet):** `https://<canister-id>.icp0.io`
- **Auth:** author writes require `Authorization: Bearer <token>`. Local dev
  default token: `pyrepress-dev-token` (the canister stores only its SHA-256
  hash; rotate via `PUT /api/meta`). Reads and the view counter are public.
- **CORS:** `Access-Control-Allow-Origin: *`; `IC-Certificate` /
  `IC-CertificateExpression` are exposed to browser JS. Preflight `OPTIONS`
  is answered automatically (204).
- **Content types:** requests are JSON; responses are JSON except
  `GET /api/feed.xml` (RSS/XML).

## Certification

Certified routes carry an `IC-Certificate` header whose witness proves the
response body against the canister's certified data (the network root of
trust, not the answering node). Certified: `GET /api/health`,
`GET /api/meta`, `GET /api/posts` (canonical first page only),
`GET /api/feed.xml`, and each **published** post's exact path
`GET /api/posts/<slug>`. Uncertified reads (`/api/posts/query`, draft
previews) are still served through the gateway under a skip-certification
witness.

Verify independently (note the 4th `connect` arg — Python can't resolve the
`<cid>.localhost` subdomain on macOS):
`python scripts/verify_certification.py http://<cid>.localhost:4943/api/posts/<slug> <cid> 127.0.0.1:4943`
→ `PASS: response verification v2 checks succeeded`.

### ⚠️ Uncertified reads and the certifying gateway

A PYRE limitation you must design around (see FRICTION.md #2): the certifying
gateway (`<cid>.localhost:4943`, `<cid>.icp0.io`) returns **`503
backend_response_verification`** for **uncertified** GET routes once certified
exact paths exist — this affects `GET /api/posts/query` and **draft**
previews. Two ways to cope, pick per view:

1. **Filter/paginate client-side** from the certified `GET /api/posts` (the
   verifiable path) — preferred for the public reading UI.
2. **Call uncertified endpoints via the `raw` subdomain**
   (`<cid>.raw.localhost:4943`, `<cid>.raw.icp0.io`), which skips gateway
   verification — fine for the author's own compose/preview screens.

Certified routes (`/api/posts`, `/api/posts/<slug>`, `/api/feed.xml`,
`/api/health`, `/api/meta`) work on both the normal and raw domains.

---

## Data shapes

### `PublicPost`
```json
{
  "id": "000000000001",
  "slug": "pyre-v1-1-announcement",
  "title": "PYRE v1.1: Python on the Internet Computer, verified",
  "html": "<p>rendered, sanitized HTML…</p>",
  "markdown": "source markdown (omitted from list responses)",
  "tags": ["pyre", "icp", "release"],
  "status": "published",
  "published_at": 1783068056,
  "updated_at": 1783068056,
  "views": 42
}
```
`published_at` / `updated_at` are epoch **seconds** (`0` = never published).
`views` is a live counter (stored outside the post document).

### `Verify` block (attached to single-post responses)
```json
{
  "certified": true,
  "canister_id": "aaaaa-aa",
  "path": "/api/posts/pyre-v1-1-announcement",
  "how": "This response carries an IC-Certificate header…",
  "verifier": "https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/scripts/verify_certification.py"
}
```

---

## Routes

### `GET /api/health` — certified
`200` → `{"status":"ok","app":"pyrepress"}`

### `GET /api/meta` — certified
`200` → `{"title","description","author","base_url"}` (blog config).

### `PUT /api/meta` — bearer
Body (all optional): `{"title","description","author","base_url","token"}`.
Sending `token` rotates the author bearer token (stores the new SHA-256 hash;
the raw token is never stored). `200` → the updated meta object.

### `GET /api/posts` — certified
Canonical newest-first first page (size 10). **Query params are ignored here**
(certification is per-path and can't vary by query string — use
`/api/posts/query`).
`200` → `{"items": PublicPost[] (no markdown), "next": <cursor|null>}`

### `GET /api/posts/query` — uncertified (query-fast)
Query params: `limit` (1–100, default 10), `after` (cursor from a previous
`next`), `tag` (exact tag membership). Newest-first, published only.
`200` → `{"items": PublicPost[] (no markdown), "next": <cursor|null>}`
`400` → `{"error":"limit must be an integer"}`

### `GET /api/posts/{slug}` — certified for published posts
- Published post → `200` `{"post": PublicPost, "verify": Verify{certified:true}}`,
  served from the post's certified exact path (`IC-Certificate` present).
- Draft → `200` **only** with a valid author bearer token
  (`verify.certified:false`); without the token it is `404` (drafts never leak).
- Unknown slug → `404` `{"error":"not found"}`.

### `POST /api/posts` — bearer
Body: `{"title": str, "markdown": str, "slug"?: str, "tags"?: str[], "status"?: "draft"|"published"}`.
`slug` defaults to a slugified title; must be `^[a-z0-9]+(?:-[a-z0-9]+)*$`,
≤100 chars, not the reserved word `query`.
- `201` → `{"post": PublicPost, "verify": Verify}`
- `400` → validation / invalid slug / bad status
- `409` → `{"error":"slug already exists","slug": "..."}`

### `PUT /api/posts/{slug}` — bearer
Partial update. Body may include any of
`{"title","markdown","slug","tags","status"}` (unknown fields → `400`).
Setting `slug` renames (and moves the certified path). First transition to
`published` stamps `published_at`.
- `200` → `{"post": PublicPost, "verify": Verify}`
- `400` unknown fields / invalid slug / bad status · `404` not found ·
  `409` slug taken

### `DELETE /api/posts/{slug}` — bearer
`200` → `{"deleted": "<slug>"}` · `404` not found.

### `POST /api/posts/{slug}/view` — public
Increments the per-post view counter (an **update** call — queries can't
write). No body. `200` → `{"slug":"...","views": <int>}` · `404` if the slug
isn't a published post.

### `GET /api/feed.xml` — certified
`200`, `Content-Type: application/rss+xml` — RSS 2.0, latest 20 published
posts, newest first.

### `POST /api/seed` — bearer
Idempotent (by slug) demo loader: inserts the announcement post + samples if
absent. `200` → `{"created": ["<slug>", …], "total_posts": <int>}`.

---

# Phase C — authenticated comments (Google OIDC)

Readers sign in with **Google** (the Phase-B gate PASSED, so real in-canister
RS256/ES256 ID-token verification via `pyre.oidc`; the Internet-Identity
fallback is NOT used). Login mints a **cheap stored session** — a 32-byte
`pyre.random.raw_bytes` token mapped to the verified identity in canister
storage. Sessions are **not** threshold-signed (SPEC §3/§6); validation is a
query-fast `O(1)` read with an expiry check. Sessions live 30 days.

- **Session auth header:** `X-Session-Id: <session_id>` (canonical, what the
  frontend sends). `Authorization: Bearer <session_id>` is also accepted on
  `/api/auth/me`. This is distinct from the **author bearer token** used for
  moderation.
- **Setup:** set the Google OAuth **Web client id** (public, the OIDC `aud`)
  once via `PUT /api/meta {"google_client_id":"…apps.googleusercontent.com"}`.
  Without it, login returns `400` (`unconfigured provider`).
- **Pluggability:** the login route selects the provider by name
  (`{"provider":"google", …}`); adding GitHub OIDC / II / FFN later is a
  registry entry (`oidc_verifiers[name] = verifier`), not a rewrite.

### `POST /api/auth/login` — public (update)
Verify an OIDC ID token and mint a session. Verification does a JWKS outcall
only on a `kid` cache-miss (steady state: zero outcalls).
Body: `{"provider": "google", "token": "<google_id_token>"}` (`token` or
`id_token` accepted).
- `200` → `{"session_id","identity","email","name","picture"}` (`identity` is
  the Google `sub`)
- `400` missing token / unknown-or-unconfigured provider ·
  `401` token failed verification (bad signature/issuer/audience/expiry) ·
  `403` email present but unverified

### `POST /api/auth/google` — public (update)
Convenience alias fixing provider=google. Body: `{"id_token": "…"}`. Same
responses as `/api/auth/login`.

### `GET /api/auth/me` — session (query-fast)
Header `X-Session-Id` (or `Authorization: Bearer <session_id>`).
- `200` → `{"session_id","identity","email","name","picture"}`
- `401` no valid / expired session

### `POST /api/auth/logout` — session
Header `X-Session-Id`. Invalidates the session. `200` → `{"ok": true}`.

### `POST /api/posts/{slug}/comments` — session (update)
Submit a comment on a **published** post. Requires a valid session
(`X-Session-Id`). Body: `{"body": "<text>"}`. Body is **capped at 2000 chars**
and **rate-limited per identity** (≤5 unreviewed pending, ≤10/hour). Stored as
`status:"pending"` — invisible until the author approves.
- `201` → the created `Comment`
  `{"id","slug","author_identity","author_name","body","ts"(ISO-8601),"status":"pending"}`
- `401` no session · `404` unknown/draft post · `413` body too long ·
  `429` rate-limited · `400` empty body

### `GET /api/posts/{slug}/comments` — certified
Approved comments for a post, oldest first. **Certified**: each published post
has a certified `GET /api/posts/<slug>/comments` route (registered alongside
the post's certified route); approving/rejecting re-certifies it via the
gateway's automatic post-update `recertify()`.
- `200` → `{"items": Comment[]}` (approved only) · `404` unknown post

### `GET /api/comments/pending` — bearer (author)
Moderation queue: all pending comments, newest first.
`200` → `{"items": Comment[]}` · `401` without the author token.
**Uncertified GET:** like `/api/posts/query`, a certifying gateway returns
`503 backend_response_verification` for this route's 2xx responses — fetch it
via the **raw** subdomain (`<cid>.raw.localhost:4943` / `.raw.icp0.io`) from
the author's moderation screen.

### `GET /api/moderation/comments?status=pending` — bearer (author)
Alias honoring `?status=pending|approved|rejected` (default `pending`).
`200` → `{"items": Comment[]}` · `400` bad status · `401` no token.

### `POST /api/comments/{id}/approve` — bearer (author)
Approve a comment (it becomes visible in the certified list). Frees one unit
of the author's pending rate budget.
`200` → `{"comment": Comment}` · `404` unknown id.

### `POST /api/comments/{id}/reject` — bearer (author)
Reject a comment (stays hidden). `200` → `{"comment": Comment}` · `404`.

## Comment auth quick reference

```bash
BASE=http://$(dfx canister id pyrepress).localhost:4943
TOKEN=pyrepress-dev-token   # author token (moderation)

# one-time: register the Google OAuth Web client id (public)
curl -X PUT $BASE/api/meta -H "Authorization: Bearer $TOKEN" \
  -d '{"google_client_id":"1234-abc.apps.googleusercontent.com"}'

# reader logs in with a Google ID token from Google Identity Services (browser)
SID=$(curl -s -X POST $BASE/api/auth/login \
  -d '{"provider":"google","token":"<google_id_token>"}' | jq -r .session_id)

# submit a comment (authenticated by the session)
curl -X POST $BASE/api/posts/hello-pyrepress/comments \
  -H "X-Session-Id: $SID" -d '{"body":"Great post!"}'

# author moderates
curl -s $BASE/api/comments/pending -H "Authorization: Bearer $TOKEN"
curl -X POST $BASE/api/comments/<id>/approve -H "Authorization: Bearer $TOKEN"

# approved comments, certified
curl -i $BASE/api/posts/hello-pyrepress/comments   # IC-Certificate present
```

---

## Auth quick reference

```bash
TOKEN=pyrepress-dev-token
BASE=http://$(dfx canister id pyrepress).localhost:4943

# create + publish
curl -X POST $BASE/api/posts -H "Authorization: Bearer $TOKEN" \
  -d '{"title":"Hi","markdown":"# Hi","status":"published"}'

# read (certified)
curl -i $BASE/api/posts/hi           # look for IC-Certificate

# view counter
curl -X POST $BASE/api/posts/hi/view

# list / filter / paginate
curl $BASE/api/posts
curl "$BASE/api/posts/query?tag=pyre&limit=5"
```
