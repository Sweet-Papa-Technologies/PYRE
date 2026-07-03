"""pyre.static — serve a built single-page app (Vite/Vue `dist/`) and its
static assets from the canister itself.

Storage model (chunked over pyre.kv)
------------------------------------
pyre.kv values are JSON strings capped at 64_000 bytes, so every asset is
chunked across many keys and reassembled on read:

    static:<path>:meta   JSON: {size, sha256, content_type, chunks,
                                gzip, gzip_size, gzip_sha256, gzip_chunks}
    static:<path>:c:<n>  base64 of one raw slice   (n = 0..chunks-1)
    static:<path>:gz:<n> base64 of one gzip slice  (n = 0..gzip_chunks-1)

`<path>` is the asset's RELATIVE path ("index.html", "assets/app-4f2a1c.js");
no leading slash, no "..", no ":" (keeps kv key parsing unambiguous).

Chunk encoding: **base64**, at a raw slice size of CHUNK_RAW_SIZE=45_000
bytes -> exactly 60_000 base64 chars -> 60_002 bytes JSON-encoded, safely
under kv's 64_000-byte cap. base64 beats a latin-1 passthrough because its
expansion is a FIXED 4/3 and the JSON string stays pure ASCII on every
interpreter; latin-1 bytes escape data-dependently under json.dumps (up to
6x for control bytes, and RustPython/CPython differ on ensure_ascii
behavior), so its worst case is far more expensive and its sizing cannot be
budgeted. base64 also lets the upload path persist client-sent chunk
strings after a single validation decode.

Gzip variants
-------------
Both the raw and (if the uploader provides it) gzipped bytes are stored.
Uncertified asset responses pick the variant per the request's
Accept-Encoding (plus `content-encoding: gzip` / `vary: accept-encoding`
headers) — these ride the skip-certification wildcard, where varying the
body is fine. The (optionally) CERTIFIED index route serves exactly ONE
canonical variant — the RAW bytes — because response certification hashes
the exact body+headers served and a snapshot cannot vary per request.

Serving — mount()
-----------------
`mount(app, prefix="/", index="index.html", spa=True, certified_index=False)`
registers:

  * GET <prefix>              exact index route (certified if requested);
                              skipped if the app already routes that path
  * GET <prefix>{path:path}   catch-all — matched at LOWER priority than
                              every other route (see pyre.routing), so API
                              routes always win regardless of registration
                              order

Behavior: exact asset -> served with content-type + cache headers; missing
path that doesn't look like a file (no dot in the last segment) with an
Accept including text/html and spa=True -> index.html (client-side
routing); anything else -> real 404 (which PYRE upgrades + serves certified
via the update path, like every non-2xx query result).

Cache-Control: content-hashed filenames (Vite's `app-4Fa9zK1c.js` pattern:
an 8+ char [-.]-separated suffix containing a digit) get
`public, max-age=31536000, immutable`; .html and the index get `no-cache`;
everything else `public, max-age=3600`. Heuristic — rename files that
false-positive.

Upload protocol — admin_routes()
--------------------------------
`admin_routes(app, token_check)` registers bearer-token-guarded routes
under /_pyre/static (POSTs are update calls; state persists):

  POST /manifest  {"assets": {path: {"size", "sha256"[, "content_type",
                  "gzip_size", "gzip_sha256"]}}}
                  -> {"chunk_size", "accepted": {path: {"chunks",
                     "gzip_chunks"}}, "rejected": {path: reason}}
                  Stages upload metadata. Assets > MAX_ASSET_BYTES are
                  rejected (reassembled responses must stay under the
                  ~2MB gateway response cap).
  POST /chunk     {"path", "index", "data": <base64>, "variant": "raw"|"gzip"}
                  Stores one staged slice. Every chunk except the last must
                  be exactly chunk_size raw bytes. Idempotent: re-sending
                  the same chunk is a no-op (safe under retries).
  POST /finalize  {"paths": [..]} (or {} for everything staged)
                  Verifies each staged asset's sha256 (per variant), then
                  atomically swaps live chunks+meta (one update call = one
                  atomic state transition on ICP; the old asset stays live
                  until the swap). sha mismatch -> error, staging kept for
                  re-upload, live asset untouched. Re-finalizing an
                  already-finalized path reports it as "skipped".
  POST /delete    {"paths": [..]} -> removes assets
  GET  /list      -> {"assets": {path: {size, sha256, gzip, content_type}},
                     "chunk_size"} (query; used by the CLI to skip
                     unchanged files)

Uploads run through http_request_update, so the gateway re-runs
app.recertify() after each one — a certified index.html snapshot is
re-certified the moment finalize commits it.

Certification note: before any upload, a certified index route serves a
200 placeholder page ("no index.html uploaded yet") — recertify() requires
2xx from certified routes, and canister init recertifies.

RustPython-safe: os.path-free, stdlib only (base64, hashlib, re, json).
"""

import base64
import hashlib
import re

from pyre import kv
from pyre.errors import BadRequest
from pyre.http_types import Response

try:
    from hmac import compare_digest as _compare_digest
except ImportError:  # pragma: no cover — minimal constant-time-ish fallback

    def _compare_digest(a, b):
        if len(a) != len(b):
            return False
        result = 0
        for x, y in zip(a, b):
            result |= ord(x) ^ ord(y)
        return result == 0


# One raw slice per kv chunk: 45_000 bytes -> exactly 60_000 base64 chars
# -> 60_002 bytes JSON-encoded, under pyre.kv's 64_000-byte value cap.
CHUNK_RAW_SIZE = 45_000

# Reassembled bodies must stay well under the ICP HTTP gateway's ~2MB
# response cap (headers + certificate share the budget). Enforced at
# manifest time; the CLI warns and skips oversized files.
MAX_ASSET_BYTES = 1_800_000

DEFAULT_ADMIN_PREFIX = "/_pyre/static"

_LIVE = "static:"
_STAGE = "staticup:"
_VARIANT_TAG = {"raw": "c", "gzip": "gz"}

# ---------------------------------------------------------------------------
# content types / cache headers
# ---------------------------------------------------------------------------

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".wasm": "application/wasm",
    ".pdf": "application/pdf",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

DEFAULT_CONTENT_TYPE = "application/octet-stream"

# Extensions worth gzipping (text-ish). Image/font/video formats are already
# compressed — gzipping them wastes upload chunks and cycles for no gain.
COMPRESSIBLE_EXTS = frozenset(
    [".html", ".htm", ".js", ".mjs", ".css", ".json", ".map", ".webmanifest",
     ".svg", ".txt", ".xml", ".wasm"]
)

# Vite-style content-hashed basename: "-4Fa9zK1c.js" / ".d1f9e0ab2c.css".
# The hashy group must contain a digit — cuts false positives like
# "font-regular2020.woff"-style names are still possible; rename those.
_HASHED_NAME = re.compile(r"[-.]([0-9A-Za-z_-]{8,})\.[A-Za-z0-9]+$")


def _ext(path):
    base = path.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return base[dot:].lower() if dot >= 0 else ""


def content_type_for(path):
    """Map a path/filename to a content-type (falls back to octet-stream)."""
    return CONTENT_TYPES.get(_ext(path), DEFAULT_CONTENT_TYPE)


def is_compressible(path):
    return _ext(path) in COMPRESSIBLE_EXTS


def cache_control_for(path):
    """Cache policy: hashed assets immutable, HTML no-cache, rest short."""
    if _ext(path) in (".html", ".htm"):
        return "no-cache"
    m = _HASHED_NAME.search(path.rsplit("/", 1)[-1])
    if m and any(ch.isdigit() for ch in m.group(1)):
        return "public, max-age=31536000, immutable"
    return "public, max-age=3600"


# ---------------------------------------------------------------------------
# paths / keys
# ---------------------------------------------------------------------------


def normalize_path(path):
    """Normalize an asset path to its stored relative form.

    Returns "" for the root, None if invalid (traversal, empty segment,
    ':' or '\\' — ':' would make kv key parsing ambiguous)."""
    if not isinstance(path, str):
        return None
    path = path.lstrip("/")
    if path == "":
        return ""
    if ":" in path or "\\" in path:
        return None
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            return None
    return path


def _meta_key(path, staging=False):
    return "%s%s:meta" % (_STAGE if staging else _LIVE, path)


def _chunk_key(path, variant, index, staging=False):
    return "%s%s:%s:%d" % (
        _STAGE if staging else _LIVE, path, _VARIANT_TAG[variant], index,
    )


def _chunk_count(size):
    if size <= 0:
        return 1  # a zero-byte asset still stores one (empty) chunk
    return (size + CHUNK_RAW_SIZE - 1) // CHUNK_RAW_SIZE


def _expected_chunk_size(total, count, index):
    if index < count - 1:
        return CHUNK_RAW_SIZE
    return total - CHUNK_RAW_SIZE * (count - 1)


# ---------------------------------------------------------------------------
# asset store (writes need update context; kv enforces that)
# ---------------------------------------------------------------------------


def _write_chunks(path, variant, data, staging=False):
    count = _chunk_count(len(data))
    for index in range(count):
        piece = data[index * CHUNK_RAW_SIZE : (index + 1) * CHUNK_RAW_SIZE]
        kv.set(
            _chunk_key(path, variant, index, staging),
            base64.b64encode(piece).decode("ascii"),
        )
    return count


def _trim_chunks(path, variant, old_count, new_count, staging=False):
    for index in range(new_count, old_count):
        kv.delete(_chunk_key(path, variant, index, staging))


def _variant_counts(meta):
    if meta is None:
        return {"raw": 0, "gzip": 0}
    return {"raw": meta.get("chunks", 0), "gzip": meta.get("gzip_chunks", 0)}


def put_asset(path, body, content_type=None, gzip_body=None):
    """Store an asset in one call (chunks + meta). Update context required.

    `body` is the raw bytes; `gzip_body` (optional) the pre-gzipped variant
    of the SAME content. Mostly for tests/seed scripts — production uploads
    go through the manifest/chunk/finalize protocol."""
    rel = normalize_path(path)
    if not rel:
        raise ValueError("invalid asset path: %r" % (path,))
    body = bytes(body)
    if len(body) > MAX_ASSET_BYTES:
        raise ValueError(
            "asset %r is %d bytes; max %d (gateway response cap)"
            % (rel, len(body), MAX_ASSET_BYTES)
        )
    old = _variant_counts(get_meta(rel))
    meta = {
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "content_type": content_type or content_type_for(rel),
        "chunks": _write_chunks(rel, "raw", body),
        "gzip": gzip_body is not None,
        "gzip_chunks": 0,
    }
    if gzip_body is not None:
        gzip_body = bytes(gzip_body)
        meta["gzip_size"] = len(gzip_body)
        meta["gzip_sha256"] = hashlib.sha256(gzip_body).hexdigest()
        meta["gzip_chunks"] = _write_chunks(rel, "gzip", gzip_body)
    kv.set(_meta_key(rel), meta)
    _trim_chunks(rel, "raw", old["raw"], meta["chunks"])
    _trim_chunks(rel, "gzip", old["gzip"], meta["gzip_chunks"])
    return meta


def get_meta(path):
    """The asset's meta dict (cheap; no chunk reassembly), or None."""
    return kv.get(_meta_key(path))


def read_asset(path, variant="raw"):
    """Reassemble an asset's bytes for one variant, or None if absent."""
    meta = get_meta(path)
    if meta is None:
        return None
    if variant == "gzip" and not meta.get("gzip"):
        return None
    count = meta["chunks"] if variant == "raw" else meta["gzip_chunks"]
    parts = []
    for index in range(count):
        encoded = kv.get(_chunk_key(path, variant, index))
        if encoded is None:
            raise ValueError("asset %r missing %s chunk %d" % (path, variant, index))
        parts.append(base64.b64decode(encoded))
    return b"".join(parts)


def list_assets():
    """Sorted relative paths of every stored asset."""
    paths = []
    for key in kv.keys():
        if key.startswith(_LIVE) and key.endswith(":meta"):
            paths.append(key[len(_LIVE) : -len(":meta")])
    return sorted(paths)


def delete_asset(path):
    """Remove an asset (meta + all chunks). Returns True if it existed."""
    counts = _variant_counts(get_meta(path))
    if not kv.delete(_meta_key(path)):
        return False
    _trim_chunks(path, "raw", counts["raw"], 0)
    _trim_chunks(path, "gzip", counts["gzip"], 0)
    return True


def clear_assets():
    """Delete every stored asset. Returns the count removed."""
    paths = list_assets()
    for path in paths:
        delete_asset(path)
    return len(paths)


# ---------------------------------------------------------------------------
# serving
# ---------------------------------------------------------------------------

_PLACEHOLDER_INDEX = (
    b"<!doctype html><html><head><title>PYRE</title></head>"
    b"<body><h1>PYRE</h1><p>No index.html uploaded yet. "
    b"Push your build with: pyre assets push dist/ --url ... --token ...</p>"
    b"</body></html>"
)


def _accepts_gzip(request):
    for part in request.headers.get("accept-encoding", "").split(","):
        token, _, params = part.strip().partition(";")
        if token.strip().lower() != "gzip":
            continue
        q = params.replace(" ", "")
        if q.startswith("q="):
            try:
                return float(q[2:]) > 0
            except ValueError:
                return True
        return True
    return False


def _wants_html(request):
    return "text/html" in request.headers.get("accept", "")


def _not_found(request):
    return Response.json({"error": "not found", "path": request.path}, status=404)


def mount(app, prefix="/", index="index.html", spa=True, certified_index=False):
    """Serve the asset store from `app` under `prefix`.

    Register API routes on the same app freely — the catch-all matches at
    lower priority than every other route. If the app already routes GET
    <prefix> exactly, that route wins and no index route is added.

    certified_index=True snapshots the index response into the v2
    certification tree (re-certified automatically after every update, so
    finalize immediately refreshes it). The certified index always serves
    the RAW variant — a certified snapshot cannot vary per Accept-Encoding.
    Asset responses stay uncertified queries riding skip-certification.
    """
    if not prefix.startswith("/"):
        raise ValueError("static prefix must start with '/': %r" % (prefix,))
    index_rel = normalize_path(index)
    if not index_rel:
        raise ValueError("invalid index filename: %r" % (index,))
    base = prefix.rstrip("/")
    root_path = base or "/"

    def pyre_static_index(request):
        meta = get_meta(index_rel)
        if meta is None:
            return Response(
                _PLACEHOLDER_INDEX,
                headers=[
                    ("content-type", "text/html; charset=utf-8"),
                    ("cache-control", "no-cache"),
                ],
            )
        return Response(
            read_asset(index_rel, "raw"),
            headers=[
                ("content-type", meta["content_type"]),
                ("cache-control", "no-cache"),
            ],
        )

    def pyre_static_asset(request):
        rel = normalize_path(request.path_params.get("path", ""))
        if rel is None:
            return _not_found(request)
        if rel == "" or rel == index_rel:
            return pyre_static_index(request)
        meta = get_meta(rel)
        if meta is None:
            filename = rel.rsplit("/", 1)[-1]
            if spa and "." not in filename and _wants_html(request):
                return pyre_static_index(request)  # client-side route
            return _not_found(request)
        use_gzip = bool(meta.get("gzip")) and _accepts_gzip(request)
        headers = [
            ("content-type", meta["content_type"]),
            ("cache-control", cache_control_for(rel)),
        ]
        if meta.get("gzip"):
            headers.append(("vary", "accept-encoding"))
        if use_gzip:
            headers.append(("content-encoding", "gzip"))
        return Response(read_asset(rel, "gzip" if use_gzip else "raw"), headers=headers)

    if app.router.match("GET", root_path)[0] is None:
        app.router.add(
            "GET", root_path, pyre_static_index, update=False, certified=certified_index
        )
    app.router.add("GET", base + "/{path:path}", pyre_static_asset, update=False)
    return {"root": root_path, "catch_all": base + "/{path:path}", "index": index_rel}


# ---------------------------------------------------------------------------
# upload protocol (authenticated update routes)
# ---------------------------------------------------------------------------


def _token_checker(token_check):
    if callable(token_check):
        return token_check
    if isinstance(token_check, str):
        return lambda token: _compare_digest(token, token_check)
    accepted = list(token_check)
    return lambda token: any(_compare_digest(token, want) for want in accepted)


def _staged_paths():
    paths = []
    for key in kv.keys():
        if key.startswith(_STAGE) and key.endswith(":meta"):
            paths.append(key[len(_STAGE) : -len(":meta")])
    return sorted(paths)


def _drop_staging(path, stage):
    counts = _variant_counts(stage)
    _trim_chunks(path, "raw", counts["raw"], 0, staging=True)
    _trim_chunks(path, "gzip", counts["gzip"], 0, staging=True)
    kv.delete(_meta_key(path, staging=True))


def _collect_staged(path, stage, variant):
    """Returns (b64_chunk_list, error_message_or_None), verifying sha256."""
    total = stage["size"] if variant == "raw" else stage["gzip_size"]
    count = stage["chunks"] if variant == "raw" else stage["gzip_chunks"]
    expected_sha = stage["sha256"] if variant == "raw" else stage["gzip_sha256"]
    encoded, decoded = [], []
    for index in range(count):
        value = kv.get(_chunk_key(path, variant, index, staging=True))
        if value is None:
            return None, "missing %s chunk %d of %d" % (variant, index, count)
        encoded.append(value)
        decoded.append(base64.b64decode(value))
    data = b"".join(decoded)
    if len(data) != total:
        return None, "%s variant is %d bytes, manifest said %d" % (
            variant, len(data), total,
        )
    if hashlib.sha256(data).hexdigest() != expected_sha:
        return None, "%s variant failed sha256 verification" % variant
    return encoded, None


def _promote(path, stage):
    """Verify a staged upload and atomically swap it live. Returns error or None."""
    raw_chunks, err = _collect_staged(path, stage, "raw")
    if err:
        return err
    gzip_chunks = []
    if stage.get("gzip"):
        gzip_chunks, err = _collect_staged(path, stage, "gzip")
        if err:
            return err
    old = _variant_counts(get_meta(path))
    for index, value in enumerate(raw_chunks):
        kv.set(_chunk_key(path, "raw", index), value)
    for index, value in enumerate(gzip_chunks):
        kv.set(_chunk_key(path, "gzip", index), value)
    meta = {
        "size": stage["size"],
        "sha256": stage["sha256"],
        "content_type": stage["content_type"],
        "chunks": len(raw_chunks),
        "gzip": bool(stage.get("gzip")),
        "gzip_chunks": len(gzip_chunks),
    }
    if meta["gzip"]:
        meta["gzip_size"] = stage["gzip_size"]
        meta["gzip_sha256"] = stage["gzip_sha256"]
    kv.set(_meta_key(path), meta)
    _trim_chunks(path, "raw", old["raw"], meta["chunks"])
    _trim_chunks(path, "gzip", old["gzip"], meta["gzip_chunks"])
    _drop_staging(path, stage)
    return None


def admin_routes(app, token_check, prefix=DEFAULT_ADMIN_PREFIX):
    """Register the authenticated upload/management routes (see module doc).

    `token_check`: a str, a container of strs, or a callable(token) -> bool.
    Tokens travel as `Authorization: Bearer <token>`; store token HASHES in
    kv if you go beyond a deploy-time secret (canister state is readable by
    node providers — see pyre.auth docs)."""
    check = _token_checker(token_check)

    def guard(request):
        header = request.headers.get("authorization", "")
        if header[:7].lower() == "bearer ":
            token = header[7:].strip()
            if token and check(token):
                return None
        return Response.json(
            {"error": "unauthorized"},
            status=401,
            headers=[("www-authenticate", 'Bearer realm="pyre-static"')],
        )

    def guarded(handler):
        def inner(request):
            denied = guard(request)
            return denied if denied is not None else handler(request)

        inner.__name__ = handler.__name__
        return inner

    def pyre_static_manifest(request):
        body = request.json()
        assets = body.get("assets")
        if not isinstance(assets, dict) or not assets:
            raise BadRequest("manifest needs a non-empty 'assets' object")
        accepted, rejected = {}, {}
        for path, spec in assets.items():
            rel = normalize_path(path)
            if not rel:
                rejected[str(path)] = "invalid path"
                continue
            if not isinstance(spec, dict):
                rejected[rel] = "asset spec must be an object"
                continue
            size, sha = spec.get("size"), spec.get("sha256")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0 \
                    or not isinstance(sha, str) or len(sha) != 64:
                rejected[rel] = "size (int) and sha256 (64-char hex) are required"
                continue
            if size > MAX_ASSET_BYTES:
                rejected[rel] = (
                    "%d bytes exceeds the %d-byte asset cap (gateway "
                    "responses top out near 2MB)" % (size, MAX_ASSET_BYTES)
                )
                continue
            gz_size, gz_sha = spec.get("gzip_size"), spec.get("gzip_sha256")
            has_gzip = gz_size is not None or gz_sha is not None
            if has_gzip and (
                not isinstance(gz_size, int) or isinstance(gz_size, bool)
                or gz_size < 0 or gz_size > MAX_ASSET_BYTES
                or not isinstance(gz_sha, str) or len(gz_sha) != 64
            ):
                rejected[rel] = "gzip variant needs valid gzip_size + gzip_sha256"
                continue
            stage = {
                "size": size,
                "sha256": sha.lower(),
                "content_type": spec.get("content_type") or content_type_for(rel),
                "chunks": _chunk_count(size),
                "gzip": has_gzip,
                "gzip_chunks": _chunk_count(gz_size) if has_gzip else 0,
            }
            if has_gzip:
                stage["gzip_size"] = gz_size
                stage["gzip_sha256"] = gz_sha.lower()
            kv.set(_meta_key(rel, staging=True), stage)
            accepted[rel] = {
                "chunks": stage["chunks"], "gzip_chunks": stage["gzip_chunks"],
            }
        status = 200 if accepted else 400
        return Response.json(
            {"chunk_size": CHUNK_RAW_SIZE, "accepted": accepted, "rejected": rejected},
            status=status,
        )

    def pyre_static_chunk(request):
        body = request.json()
        rel = normalize_path(body.get("path", ""))
        variant = body.get("variant", "raw")
        index = body.get("index")
        data = body.get("data")
        if not rel or variant not in _VARIANT_TAG or not isinstance(data, str) \
                or not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise BadRequest("chunk needs path, index (int), data (base64)")
        stage = kv.get(_meta_key(rel, staging=True))
        if stage is None:
            raise BadRequest("no pending manifest for %r — POST /manifest first" % rel)
        if variant == "gzip" and not stage.get("gzip"):
            raise BadRequest("manifest declared no gzip variant for %r" % rel)
        total = stage["size"] if variant == "raw" else stage["gzip_size"]
        count = stage["chunks"] if variant == "raw" else stage["gzip_chunks"]
        if index >= count:
            raise BadRequest("chunk index %d out of range (%d chunks)" % (index, count))
        try:
            decoded = base64.b64decode(data)
        except Exception:
            raise BadRequest("chunk data is not valid base64")
        expected = _expected_chunk_size(total, count, index)
        if len(decoded) != expected:
            raise BadRequest(
                "chunk %d must be %d bytes, got %d" % (index, expected, len(decoded))
            )
        # store the canonical re-encoding; identical re-uploads are no-ops
        kv.set(
            _chunk_key(rel, variant, index, staging=True),
            base64.b64encode(decoded).decode("ascii"),
        )
        return Response.json({"ok": True, "path": rel, "variant": variant, "index": index})

    def pyre_static_finalize(request):
        body = request.json() if request.body else {}
        requested = body.get("paths")
        finalized, skipped, errors = [], [], {}
        if requested is None:
            targets = _staged_paths()
        else:
            targets = [normalize_path(p) for p in requested]
        for rel in targets:
            if not rel:
                errors[str(rel)] = "invalid path"
                continue
            stage = kv.get(_meta_key(rel, staging=True))
            if stage is None:
                if get_meta(rel) is not None:
                    skipped.append(rel)  # idempotent re-finalize
                else:
                    errors[rel] = "nothing staged and nothing live"
                continue
            err = _promote(rel, stage)
            if err:
                errors[rel] = err  # staging kept: re-send bad chunks, retry
            else:
                finalized.append(rel)
        return Response.json(
            {"finalized": finalized, "skipped": skipped, "errors": errors},
            status=200 if not errors else 400,
        )

    def pyre_static_delete(request):
        body = request.json()
        paths = body.get("paths")
        if not isinstance(paths, list):
            raise BadRequest("delete needs {'paths': [..]}")
        deleted = []
        for path in paths:
            rel = normalize_path(path)
            if rel and delete_asset(rel):
                deleted.append(rel)
        return Response.json({"deleted": deleted})

    def pyre_static_list(request):
        summary = {}
        for path in list_assets():
            meta = get_meta(path)
            summary[path] = {
                "size": meta["size"],
                "sha256": meta["sha256"],
                "gzip": bool(meta.get("gzip")),
                "gzip_sha256": meta.get("gzip_sha256"),
                "content_type": meta["content_type"],
            }
        return Response.json({"assets": summary, "chunk_size": CHUNK_RAW_SIZE})

    app.router.add("POST", prefix + "/manifest", guarded(pyre_static_manifest))
    app.router.add("POST", prefix + "/chunk", guarded(pyre_static_chunk))
    app.router.add("POST", prefix + "/finalize", guarded(pyre_static_finalize))
    app.router.add("POST", prefix + "/delete", guarded(pyre_static_delete))
    app.router.add("GET", prefix + "/list", guarded(pyre_static_list), update=False)
    return prefix
