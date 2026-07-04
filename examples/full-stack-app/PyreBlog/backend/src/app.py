"""PyrePress Phase A — certified blog backend on PYRE.

API contract (everything under /api so an SPA catch-all can't collide):

  GET    /api/health                 certified   liveness
  GET    /api/meta                   certified   blog config
  PUT    /api/meta                   bearer      update config / rotate token
  GET    /api/posts                  certified   canonical first page (no params)
  GET    /api/posts/query            -           live list: ?limit&after&tag
  GET    /api/posts/{slug}           certified*  published post (+ verify info)
  POST   /api/posts                  bearer      create
  PUT    /api/posts/{slug}           bearer      partial update / rename
  DELETE /api/posts/{slug}           bearer      delete
  POST   /api/posts/{slug}/view      -           increment view counter
  GET    /api/feed.xml               certified   RSS 2.0, latest 20
  POST   /api/seed                   bearer      idempotent demo content

(*) Certified routes must be static paths, so each PUBLISHED post's exact
path (/api/posts/<actual-slug>) is registered as a certified route at
publish time; the gateway's automatic post-update recertify() snapshots it
in the same update call. The parametric route below is the fallback for
drafts (bearer-gated preview) and unknown slugs. `sync_certified_routes()`
rebuilds the dynamic registrations at @init/@post_upgrade (see main.py) —
runtime-registered routes don't survive an upgrade; the posts in stable
memory do.
"""

import hashlib
import re
from hmac import compare_digest

from pyre import App, Request, Response, auth, kv, oidc, static, validate
from pyre import time as ptime

from pyrepress import comments as comment_model
from pyrepress import config, feed
from pyrepress import posts as model
from pyrepress import seeds
from pyrepress import sessions

app = App()

# CORS: the Vite dev server (http://localhost:5173) and any reader UI must be
# able to call the API. Public read API, token (not cookie) auth → "*" is
# safe; tighten to the frontend origin in production if you prefer.
# ic-certificate headers are exposed so a browser client can verify responses.
app.enable_cors(
    origins="*",
    expose_headers=("ic-certificate", "ic-certificateexpression"),
)


# --- auth: bearer token on all writes, reads exempt ---------------------------
# auth.require_token(exempt=...) only takes exact paths, so wrap it: reads
# (GET/HEAD/OPTIONS) and the anonymous view counter pass through, every other
# write hits the token check. Only the sha256 of the token is stored/compared.

def _token_ok(token):
    stored = kv.get(config.TOKEN_HASH_KEY) or config.DEFAULT_TOKEN_SHA256
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return compare_digest(digest.encode(), stored.encode())


_token_hook = auth.require_token(valid=_token_ok)
_VIEW_PATH = re.compile(r"^/api/posts/[^/]+/view$")
# Phase C: comment submit is authenticated by a SESSION (checked in-handler),
# not by the author bearer token, so it is exempt from the write guard.
_COMMENT_SUBMIT_PATH = re.compile(r"^/api/posts/[^/]+/comments$")
# Phase C: login/logout mint or clear a session; they carry no author token.
_SESSION_OPEN_PATHS = {"/api/auth/login", "/api/auth/google", "/api/auth/logout"}
_WRITE_METHODS = ("POST", "PUT", "DELETE", "PATCH")


_STATIC_ADMIN_PREFIX = static.DEFAULT_ADMIN_PREFIX + "/"  # "/_pyre/static/"


@app.before_request
def _guard_writes(req):
    if req.method not in _WRITE_METHODS:
        return None  # reads are public
    if req.path.startswith(_STATIC_ADMIN_PREFIX):
        return None  # static upload routes carry their OWN bearer guard
        # (static.admin_routes); the author token must not gate SPA uploads.
    if _VIEW_PATH.match(req.path):
        return None  # anonymous view counter
    if req.path in _SESSION_OPEN_PATHS:
        return None  # session-minting auth routes (no bearer)
    if _COMMENT_SUBMIT_PATH.match(req.path):
        return None  # session-authenticated comment submit (checked in-handler)
    return _token_hook(req)


def _bearer_ok(req):
    """True if the request carries a valid author token (for draft preview)."""
    value = req.headers.get("authorization") or ""
    if not value.lower().startswith("bearer "):
        return False
    return _token_ok(value[7:].strip())


# --- per-post certified routes -------------------------------------------------
# Certified routes are static-path only; the router accepts runtime
# registration, so each published post gets its exact path registered as a
# certified route. Router matching is first-match and the parametric
# /api/posts/{slug} route is registered earlier, so exact paths are moved to
# the FRONT of the route list to take precedence.

def _post_path(slug):
    return "/api/posts/%s" % slug


def _canister_id():
    try:  # host CPython (pyre dev / pytest) has no kybra runtime
        from kybra import ic

        return ic.id().to_str()
    except Exception:  # noqa: BLE001
        return None


def _verify_info(slug, certified):
    return {
        "certified": certified,
        "canister_id": _canister_id(),
        "path": _post_path(slug),
        "how": (
            "This response carries an IC-Certificate header. Verify the "
            "body against the Internet Computer root key with any "
            "response-verification implementation (e.g. the npm package "
            "@dfinity/response-verification), giving it the canister id, "
            "the path, and the raw response."
            if certified
            else "This read is served skip-certification (draft preview or "
            "filtered query); the canonical certified copy lives at the "
            "published post's exact path."
        ),
        "verifier": "https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/scripts/verify_certification.py",
    }


def _post_body(doc, certified):
    return {
        "post": model.public_post(doc),
        "verify": _verify_info(doc["slug"], certified),
    }


def _certified_post_handler(slug):
    def certified_post(req, _slug=slug):
        doc = model.get_by_slug(_slug)
        if doc is None or doc["status"] != "published":
            # writes unregister before this can happen; 404 keeps a stale
            # registration from poisoning recertify() (it requires 2xx)
            return Response.json({"error": "not found"}, status=404)
        return Response.json(_post_body(doc, certified=True))

    return certified_post


def _certified_paths():
    return {r.path for r in app.router.routes if r.certified}


def register_certified_post(slug):
    path = _post_path(slug)
    if path not in _certified_paths():
        app.router.add("GET", path, _certified_post_handler(slug), certified=True)
        # exact paths must beat the earlier-registered /api/posts/{slug} template
        app.router.routes.insert(0, app.router.routes.pop())
    # a published post also gets a certified approved-comments list (Phase C)
    register_certified_comments(slug)


def unregister_certified_post(slug):
    path = _post_path(slug)
    app.router.routes = [
        r for r in app.router.routes if not (r.certified and r.path == path)
    ]
    if app.certification is not None:
        # evict the stale snapshot so the next recertify drops it from the tree
        app.certification.responses.pop(path, None)
    unregister_certified_comments(slug)


_TOKEN_RESET_MARKER = "auth:token_reset_2026_07_04"
# sha256 of a fresh strong author token; the plaintext lives ONLY in the
# operator's macOS Keychain (`pyrepress-author-token`), never in source.
_TOKEN_RESET_HASH = "b9e55c324d52c78990bc92e27ec9537a4771ade53d189303b10f835577df8ccf"


def reset_author_token_once():
    """Author-token reset completed 2026-07-04: the previously-rotated strong
    token was lost, so a fresh one (sha256 `_TOKEN_RESET_HASH`; plaintext in the
    operator's Keychain only) was set on-chain and the marker below recorded.
    Now a guarded no-op — future @post_upgrade runs leave the token untouched so
    a later `PUT /api/meta {"token": …}` rotation survives upgrades. Also clears
    the one-time diagnostic `reset_stamp` from meta. Uses the module's `kv`
    binding (referencing `pyre.kv` inside a canister method traps under Kybra's
    bundler)."""
    if kv.get(_TOKEN_RESET_MARKER) is None:
        kv.set(config.TOKEN_HASH_KEY, _TOKEN_RESET_HASH)
        kv.set(_TOKEN_RESET_MARKER, True)
    meta = kv.get(config.META_KEY)
    if isinstance(meta, dict) and meta.pop("reset_stamp", None) is not None:
        kv.set(config.META_KEY, meta)


def sync_certified_routes():
    """(Re-)register a certified route per published post.

    Idempotent. Called from main.py at @init/@post_upgrade, and after seed
    loading. Individual writes maintain the route set incrementally.
    """
    for doc in model.published_posts():
        register_certified_post(doc["slug"])


# --- health & meta ---------------------------------------------------------------


@app.get("/api/health", certified=True)
def health(req: Request) -> Response:
    return Response.json({"status": "ok", "app": "pyrepress"})


def _meta():
    stored = kv.get(config.META_KEY) or {}
    merged = dict(config.DEFAULT_META)
    merged.update(stored)
    return merged


@app.get("/api/meta", certified=True)
def get_meta(req: Request) -> Response:
    return Response.json(_meta())


@app.put("/api/meta")
def put_meta(req: Request) -> Response:
    body = req.json()
    clean = validate(
        body,
        {
            "title": (str, ""),
            "description": (str, ""),
            "author": (str, ""),
            "base_url": (str, ""),
            "token": (str, ""),  # rotation: stores sha256, never the token
            "google_client_id": (str, ""),  # Phase C: OIDC audience (public)
        },
    )
    if clean["token"]:
        kv.set(
            config.TOKEN_HASH_KEY,
            hashlib.sha256(clean["token"].encode("utf-8")).hexdigest(),
        )
    if "google_client_id" in body:
        kv.set(config.GOOGLE_CLIENT_ID_KEY, clean["google_client_id"])
    if "dev_login" in body:  # LOCAL-ONLY test hook (see _DevTokenVerifier)
        kv.set(config.DEV_LOGIN_KEY, bool(body["dev_login"]))
    meta = _meta()
    for field in ("title", "description", "author", "base_url"):
        if field in body:  # only fields the caller actually sent
            meta[field] = clean[field]
    kv.set(config.META_KEY, meta)
    return Response.json(meta)


# --- posts: reads ------------------------------------------------------------------


def _list_body(page):
    return {
        "items": [model.public_post(d, include_markdown=False) for d in page["items"]],
        "next": page["next"],
    }


@app.get("/api/posts", certified=True)
def list_posts(req: Request) -> Response:
    """Canonical certified first page. Query params are NOT honored here —
    certification is per path and ignores query strings. Use
    /api/posts/query for pagination and tag filtering."""
    return Response.json(
        _list_body(model.list_published(limit=config.FIRST_PAGE_LIMIT))
    )


@app.get("/api/posts/query", update=True)  # F16: uncertified 2xx GETs 503 behind
def query_posts(req: Request) -> Response:  # the certifying gateway — serve as a
    # consensus-certified update instead (this list is not a hot path).
    try:
        limit = int(req.query.get("limit", str(config.FIRST_PAGE_LIMIT)))
    except ValueError:
        return Response.json({"error": "limit must be an integer"}, status=400)
    page = model.list_published(
        limit=limit,
        after=req.query.get("after"),
        tag=req.query.get("tag"),
    )
    return Response.json(_list_body(page))


@app.get("/api/posts/{slug}")
def get_post(req: Request) -> Response:
    """Fallback read: drafts (bearer-gated preview) and unknown slugs.

    Published posts normally never reach this handler — their exact path is
    a certified route registered ahead of this one."""
    slug = req.path_params["slug"]
    doc = model.get_by_slug(slug)
    if doc is None:
        return Response.json({"error": "not found"}, status=404)
    if doc["status"] != "published" and not _bearer_ok(req):
        return Response.json({"error": "not found"}, status=404)  # don't leak drafts
    return Response.json(_post_body(doc, certified=doc["status"] == "published"))


# --- posts: writes (bearer-gated by the before-hook) -------------------------------


def _slug_error(exc):
    if isinstance(exc, model.SlugTaken):
        return Response.json(
            {"error": "slug already exists", "slug": str(exc)}, status=409
        )
    return Response.json({"error": "invalid slug", "message": str(exc)}, status=400)


@app.post("/api/posts")
def create_post(req: Request) -> Response:
    clean = validate(
        req.json(),
        {
            "title": str,
            "markdown": str,
            "slug": (str, ""),
            "tags": ([str], []),
            "status": (str, "draft"),
        },
    )
    if clean["status"] not in model.STATUSES:
        return Response.json(
            {"error": "status must be 'draft' or 'published'"}, status=400
        )
    try:
        doc = model.create_post(
            title=clean["title"],
            markdown=clean["markdown"],
            slug=clean["slug"] or None,
            tags=clean["tags"],
            status=clean["status"],
        )
    except (model.SlugInvalid, model.SlugTaken) as exc:
        return _slug_error(exc)
    if doc["status"] == "published":
        register_certified_post(doc["slug"])  # auto-recertify snapshots it
    return Response.json(
        _post_body(doc, certified=doc["status"] == "published"), status=201
    )


@app.put("/api/posts/{slug}")
def update_post(req: Request) -> Response:
    slug = req.path_params["slug"]
    body = req.json()
    allowed = {
        "title": str,
        "markdown": str,
        "slug": str,
        "tags": [str],
        "status": str,
    }
    unknown = set(body) - set(allowed)
    if unknown:
        return Response.json(
            {"error": "unknown fields", "fields": sorted(unknown)}, status=400
        )
    clean = validate(body, {k: v for k, v in allowed.items() if k in body})
    if "status" in clean and clean["status"] not in model.STATUSES:
        return Response.json(
            {"error": "status must be 'draft' or 'published'"}, status=400
        )
    try:
        old, doc = model.update_post(slug, clean)
    except KeyError:
        return Response.json({"error": "not found"}, status=404)
    except (model.SlugInvalid, model.SlugTaken) as exc:
        return _slug_error(exc)
    # keep the certified route set in sync with (slug, status)
    if old["status"] == "published" and (
        doc["status"] != "published" or doc["slug"] != old["slug"]
    ):
        unregister_certified_post(old["slug"])
    if doc["status"] == "published":
        register_certified_post(doc["slug"])
    return Response.json(_post_body(doc, certified=doc["status"] == "published"))


@app.delete("/api/posts/{slug}")
def delete_post(req: Request) -> Response:
    slug = req.path_params["slug"]
    doc = model.delete_post(slug)
    if doc is None:
        return Response.json({"error": "not found"}, status=404)
    unregister_certified_post(slug)
    return Response.json({"deleted": slug})


# --- author admin: full-fidelity views incl. drafts (bearer-gated) ------------------
# The SPA's compose/moderate views need every field (markdown + html + draft
# status) and the full list including drafts. These map from the frontend's
# root-relative /admin/* calls once VITE_API_BASE=/api is baked into the build.
# GETs are marked update=True (F16): an uncertified 2xx GET query 503s behind
# the certifying gateway once certified routes exist, so these author-only,
# non-hot reads serve as consensus-certified updates instead.


def _admin_post(doc):
    """AdminPost wire shape (frontend/src/api/types.ts): the full post — id,
    slug, title, markdown, html, tags, status, published_at, updated_at,
    views — plus schema_version and a reader URL. Author-only (exposes drafts
    and raw markdown), so every route returning it is bearer-gated."""
    out = model.public_post(doc, include_markdown=True)
    out["schema_version"] = model.SCHEMA_VERSION
    out["url"] = "/post/%s" % doc["slug"]  # SPA reader route
    return out


@app.get("/api/admin/posts", update=True)
def admin_list_posts(req: Request) -> Response:
    """All posts including drafts, newest-touched first (AdminPostList)."""
    if not _bearer_ok(req):
        return Response.json({"error": "unauthorized"}, status=401,
                             headers=[("www-authenticate", "Bearer")])
    docs = model.all_posts()
    docs.sort(key=lambda d: (d["updated_at"], d["id"]), reverse=True)
    return Response.json(
        {"items": [_admin_post(d) for d in docs], "total": len(docs)}
    )


@app.get("/api/admin/posts/{slug}", update=True)
def admin_get_post(req: Request) -> Response:
    """Any post including a draft, for editing (AdminPost)."""
    if not _bearer_ok(req):
        return Response.json({"error": "unauthorized"}, status=401,
                             headers=[("www-authenticate", "Bearer")])
    doc = model.get_by_slug(req.path_params["slug"])
    if doc is None:
        return Response.json({"error": "not found"}, status=404)
    return Response.json(_admin_post(doc))


@app.post("/api/posts/{slug}/publish")
def publish_post(req: Request) -> Response:
    """Publish a post: set status=published (published_at on first publish),
    (re-)register + recertify its certified route, return the AdminPost.

    Bearer-gated by the _guard_writes before-hook (a non-exempt write path).
    Thin wrapper over the model's status transition so the SPA has a verb-y
    endpoint instead of PUT-ing a status field."""
    slug = req.path_params["slug"]
    try:
        old, doc = model.update_post(slug, {"status": "published"})
    except KeyError:
        return Response.json({"error": "not found"}, status=404)
    # keep the certified route set in sync with (slug, status) — the gateway
    # auto-recertifies after this update, snapshotting the published post.
    if old["status"] == "published" and doc["slug"] != old["slug"]:
        unregister_certified_post(old["slug"])
    register_certified_post(doc["slug"])
    return Response.json(_admin_post(doc))


# --- analytics: the hot write never rewrites the post document ---------------------


@app.post("/api/posts/{slug}/view")
def count_view(req: Request) -> Response:
    slug = req.path_params["slug"]
    doc = model.get_by_slug(slug)
    if doc is None or doc["status"] != "published":
        return Response.json({"error": "not found"}, status=404)
    return Response.json({"slug": slug, "views": model.incr_views(doc["id"])})


# --- RSS ----------------------------------------------------------------------------


@app.get("/api/feed.xml", certified=True)
def feed_xml(req: Request) -> Response:
    docs = model.published_posts()[: config.FEED_LIMIT]
    body = feed.build_feed(_meta(), docs)
    return Response(
        body.encode("utf-8"),
        content_type="application/rss+xml; charset=utf-8",
    )


# --- seed content --------------------------------------------------------------------


@app.post("/api/seed")
def seed(req: Request) -> Response:
    created = seeds.load()
    sync_certified_routes()
    return Response.json({"created": created, "total_posts": len(model.all_posts())})


# =====================================================================================
# --- INTEGRATION SEAM: static SPA serving --------------------------------------------
# The Vue SPA is served from THIS canister via pyre.static — see the mount at
# the very bottom of this file (registered after every /api route). All API
# routes live under /api/, and the static catch-all matches at strictly lower
# priority than any other route (pyre.routing), so a catch-all cannot collide
# with them.
# =====================================================================================

# =====================================================================================
# --- PHASE C: OIDC auth, sessions, comments ------------------------------------------
# Auth flow (SPEC §4 Phase C, Google-OIDC path from the Phase-B gate):
#   POST /api/auth/login  {provider,token}  -> verify id_token, mint session
#   POST /api/auth/google {id_token}         -> convenience alias for google
#   GET  /api/auth/me      (X-Session-Id)    -> current identity (query-fast)
#   POST /api/auth/logout                    -> invalidate session
#   POST /api/posts/{slug}/comments          -> authenticated submit (session)
#   GET  /api/posts/{slug}/comments          -> approved comments, CERTIFIED
#   GET  /api/comments/pending               -> moderation queue (bearer)
#   GET  /api/moderation/comments?status=…   -> moderation queue (bearer, alias)
#   POST /api/comments/{id}/approve|reject   -> moderate (bearer)
# =====================================================================================

# --- pluggable OIDC providers (§4 pluggability) --------------------------------------
# `oidc_verifiers` maps a provider name to any object exposing an awaitable
# `verify(id_token) -> claims`. google is resolved lazily from the configured
# client id (kv, so it survives upgrades and needs no import-time binding);
# adding GitHub/II/FFN later is a registry entry, not a rewrite. Tests inject a
# mock verifier by assigning oidc_verifiers["google"] = <mock>.

oidc_verifiers = {}
_google_verifier_cache = {}


def _google_client_id():
    return kv.get(config.GOOGLE_CLIENT_ID_KEY) or config.DEFAULT_GOOGLE_CLIENT_ID


def _google_verifier():
    client_id = _google_client_id()
    if not client_id:
        return None  # not configured — real Google login unavailable
    verifier = _google_verifier_cache.get(client_id)
    if verifier is None:
        verifier = oidc.OidcVerifier(oidc.google(client_id=client_id))
        _google_verifier_cache[client_id] = verifier
    return verifier


class _DevTokenVerifier:
    """LOCAL-ONLY test provider (SPEC §4 pluggability / the Phase-C test hook).

    Turns a PLAINTEXT token into claims with NO signature verification, so the
    session/comment/moderation loop can be exercised end-to-end on a local
    replica without a real Google ID token. The REAL in-canister RS256/ES256
    verify path is proven separately (natively) in examples/oidc_spike.

    Token format: "sub|email|name" (email/name optional). Enabled only when the
    `auth:dev_login` kv flag is truthy — OFF by default, so it can never mint
    sessions on a default/mainnet deploy. NEVER enable it on mainnet.
    """

    async def verify(self, id_token):
        sub, _, rest = id_token.partition("|")
        sub = sub.strip()
        if not sub:
            raise oidc.MalformedToken("dev token needs a non-empty subject")
        email, _, name = rest.partition("|")
        email = email.strip() or ("%s@dev.local" % sub)
        return {
            "sub": sub,
            "email": email,
            "email_verified": True,
            "name": name.strip() or sub,
        }


def _dev_login_enabled():
    return bool(kv.get(config.DEV_LOGIN_KEY))


def _resolve_verifier(provider):
    if provider in oidc_verifiers:  # explicit registration / test mock wins
        return oidc_verifiers[provider]
    if provider == "google":
        return _google_verifier()
    if provider == "dev" and _dev_login_enabled():
        return _DevTokenVerifier()  # local e2e only; gated OFF by default
    return None


# --- auth routes ---------------------------------------------------------------------


async def _login(req, provider):
    body = req.json()
    id_token = body.get("token") or body.get("id_token")
    if not id_token:
        return Response.json({"error": "missing id token"}, status=400)
    verifier = _resolve_verifier(provider)
    if verifier is None:
        return Response.json(
            {"error": "unsupported or unconfigured provider", "provider": provider},
            status=400,
        )
    try:
        claims = await verifier.verify(id_token)
    except oidc.OidcError as exc:
        return Response.json({"error": str(exc)}, status=exc.status)
    # Google marks unverified emails; treat identity as the stable `sub`.
    if claims.get("email") and claims.get("email_verified") is False:
        return Response.json({"error": "email not verified"}, status=403)
    session_id, record = await sessions.mint(
        identity=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
        picture=claims.get("picture"),
        provider=provider,
    )
    return Response.json(sessions.public_session(session_id, record))


@app.post("/api/auth/login")
async def auth_login(req: Request) -> Response:
    return await _login(req, req.json().get("provider", "google"))


@app.post("/api/auth/google")
async def auth_google(req: Request) -> Response:
    """Convenience alias: POST {id_token} -> Google session (SPEC §4)."""
    return await _login(req, "google")


@app.get("/api/auth/me")
def auth_me(req: Request) -> Response:
    """Query-fast session check: an O(1) kv read + expiry test."""
    session_id, record = sessions.from_request(req)
    if record is None:
        return Response.json({"error": "no valid session"}, status=401)
    return Response.json(sessions.public_session(session_id, record))


@app.post("/api/auth/logout")
def auth_logout(req: Request) -> Response:
    session_id, _ = sessions.from_request(req)
    sessions.revoke(session_id)
    return Response.json({"ok": True})


# --- comments: certified approved list ------------------------------------------------
# Mirrors the per-post certified-route machinery: each published post gets a
# certified GET /api/posts/<slug>/comments serving its approved comments.
# Approving/rejecting is an update, after which the gateway auto-recertifies
# every certified route, so the approved list is always verifiable & current.


def _comments_path(slug):
    return "/api/posts/%s/comments" % slug


def _comments_body(slug):
    return {"items": [comment_model.public_comment(c)
                      for c in comment_model.approved_for_slug(slug)]}


def _certified_comments_handler(slug):
    def certified_comments(req, _slug=slug):
        doc = model.get_by_slug(_slug)
        if doc is None or doc["status"] != "published":
            return Response.json({"error": "not found"}, status=404)
        return Response.json(_comments_body(_slug))

    return certified_comments


def register_certified_comments(slug):
    path = _comments_path(slug)
    if path in _certified_paths():
        return
    app.router.add("GET", path, _certified_comments_handler(slug), certified=True)
    # beat the parametric /api/posts/{slug}/comments template registered below
    app.router.routes.insert(0, app.router.routes.pop())


def unregister_certified_comments(slug):
    path = _comments_path(slug)
    app.router.routes = [
        r for r in app.router.routes if not (r.certified and r.path == path)
    ]
    if app.certification is not None:
        app.certification.responses.pop(path, None)


@app.get("/api/posts/{slug}/comments")
def list_comments(req: Request) -> Response:
    """Parametric fallback (drafts / unknown slugs / uncertified serving).
    Published posts are normally served from the certified exact route."""
    slug = req.path_params["slug"]
    doc = model.get_by_slug(slug)
    if doc is None:
        return Response.json({"error": "not found"}, status=404)
    return Response.json(_comments_body(slug))


# --- comments: authenticated submit ---------------------------------------------------


@app.post("/api/posts/{slug}/comments")
def submit_comment(req: Request) -> Response:
    slug = req.path_params["slug"]
    _sid, session = sessions.from_request(req)
    if session is None:
        return Response.json(
            {"error": "authentication required"},
            status=401,
            headers=[("www-authenticate", "Session")],
        )
    doc = model.get_by_slug(slug)
    if doc is None or doc["status"] != "published":
        return Response.json({"error": "not found"}, status=404)
    body = req.json() or {}
    try:
        comment = comment_model.submit(
            slug=slug,
            author_sub=session["identity"],
            author_name=session["name"],
            author_email=session["email"],
            body=body.get("body", ""),
        )
    except comment_model.BodyTooLong as exc:
        return Response.json({"error": str(exc)}, status=413)
    except comment_model.RateLimited as exc:
        return Response.json({"error": str(exc)}, status=429)
    except ValueError as exc:
        return Response.json({"error": str(exc)}, status=400)
    # Pending comments never affect the certified approved list; no re-register.
    return Response.json(comment_model.public_comment(comment), status=201)


# --- comments: moderation (author, bearer-gated) --------------------------------------


def _pending_list():
    return {"items": [comment_model.public_comment(c) for c in comment_model.pending()]}


@app.get("/api/comments/pending", update=True)  # F16: consensus-certified update
def list_pending_comments(req: Request) -> Response:
    if not _bearer_ok(req):
        return Response.json({"error": "unauthorized"}, status=401,
                             headers=[("www-authenticate", "Bearer")])
    return Response.json(_pending_list())


@app.get("/api/moderation/comments", update=True)  # F16: consensus-certified update
def moderation_comments(req: Request) -> Response:
    """Alias of /api/comments/pending honoring ?status= (SPEC §4 Phase C)."""
    if not _bearer_ok(req):
        return Response.json({"error": "unauthorized"}, status=401,
                             headers=[("www-authenticate", "Bearer")])
    status = req.query.get("status", comment_model.STATUS_PENDING)
    if status not in comment_model.STATUSES:
        return Response.json({"error": "invalid status"}, status=400)
    items = [c for c in comment_model._all() if c["status"] == status]
    items.sort(key=lambda d: (d["ts"], d["id"]), reverse=True)
    return Response.json({"items": [comment_model.public_comment(c) for c in items]})


def _moderate(req, action):
    comment_id = req.path_params["id"]
    updated = action(comment_id)
    if updated is None:
        return Response.json({"error": "not found"}, status=404)
    # approving/rejecting changes the certified approved list; the gateway
    # auto-recertifies after this update, refreshing the post's comments route.
    return Response.json({"comment": comment_model.public_comment(updated)})


@app.post("/api/comments/{id}/approve")
def approve_comment(req: Request) -> Response:
    return _moderate(req, comment_model.approve)


@app.post("/api/comments/{id}/reject")
def reject_comment(req: Request) -> Response:
    return _moderate(req, comment_model.reject)


# Rebuild dynamic certified routes for any state that already exists. On the
# canister, main.py calls sync_certified_routes() again at @init/@post_upgrade
# (kv isn't bound yet when this module is first imported there); in `pyre dev`
# and tests this is a no-op on an empty store.
sync_certified_routes()


# =====================================================================================
# --- STATIC: serve the Vue SPA from this canister (registered LAST) ------------------
# Registered after every /api route. The static catch-all matches at strictly
# lower priority than any other route (pyre.routing), so /api/* always resolve
# to their handlers regardless of registration order; an unknown non-file path
# that accepts text/html falls back to index.html for client-side routing.
#   - admin_routes: bearer-gated /_pyre/static upload API for `pyre assets push`
#   - mount(certified_index=True): the SPA entry point is snapshotted into the
#     v2 certification tree (re-certified automatically after each upload), so
#     GET / carries an IC-Certificate; assets ride the skip-certification
#     wildcard as fast uncertified queries.
# main.py binds pyre_kv_store (which pyre.static reuses) before dispatch.
# =====================================================================================

static.admin_routes(app, config.STATIC_UPLOAD_TOKEN)
_static_mount = static.mount(
    app, prefix="/", index="index.html", spa=True, certified_index=True
)

# F16 workaround for the static asset catch-all. pyre.static.mount registers
# the catch-all (assets + SPA deep-link fallback) as an uncertified 2xx GET
# *query*. Behind the certifying (non-raw) gateway, an uncertified 2xx GET
# query 503s once any certified route exists (exactly the F16 symptom the /api
# reads hit) — assets serve only via the .raw domain. Re-flag the catch-all as
# an update so it is served consensus-certified through the NORMAL gateway.
# The certified "/" index stays a fast certified query (carries IC-Certificate).
# FRAMEWORK NOTE (for the coordinator — do NOT patch pyre/ here): pyre.static
# .mount should accept an `update=` flag for its catch-all so this post-mount
# mutation isn't needed.
for _route in app.router.routes:
    if _route.path == _static_mount["catch_all"] and not _route.certified:
        _route.update = True
