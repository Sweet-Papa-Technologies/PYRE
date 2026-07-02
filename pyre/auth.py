"""Auth middleware (WS-C): bearer / API-key / Basic checks as before-hooks.

    from pyre import auth

    app.before_request(auth.require_token(
        valid={"dev-token-1"},              # a set of tokens, or a callable
        exempt=("/health",),                # paths that stay open
    ))

    app.before_request(auth.require_basic(
        users={"alice": hashlib.sha256(b"s3cret").hexdigest()},
        exempt=("/health",),
    ))

`valid` may be a container of accepted tokens or a callable
token -> bool (e.g. lambda t: kv.get("apikey:%s" % t) is not None).

Tokens are read from `Authorization: Bearer <token>` by default; pass
header="x-api-key", scheme=None for API-key style.

Full Internet Identity login is deliberately v1.x — this covers the
"real endpoints aren't wide open" bar for v1.0.

Confidentiality note (WS-C guardrail): canister state is readable by node
providers. Store token HASHES, not tokens, for anything beyond dev:

    import hashlib
    kv.set("apikey:%s" % hashlib.sha256(token.encode()).hexdigest(), {"owner": "..."})
    app.before_request(auth.require_token(
        valid=lambda t: kv.get("apikey:%s" % hashlib.sha256(t.encode()).hexdigest()) is not None))
"""

import base64
import hashlib

from pyre.http_types import Response

try:
    # RustPython ships hmac.py and implements _operator._compare_digest
    # natively, so this import works both on host CPython and on-chain.
    from hmac import compare_digest as _compare_digest
except ImportError:  # pragma: no cover — belt-and-braces for minimal runtimes

    def _compare_digest(a, b):
        """Constant-time bytes equality: no early exit on mismatch."""
        result = 0 if len(a) == len(b) else 1
        b = b if len(a) == len(b) else a  # burn comparable time on length mismatch
        for x, y in zip(a, b):
            result |= x ^ y
        return result == 0


def _ct_equal(a, b):
    """Constant-time equality on str inputs, compared as UTF-8 bytes.

    compare_digest rejects non-ASCII str arguments, so encode first —
    RFC 7617 credentials are UTF-8.
    """
    return _compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _extract_token(request, header, scheme):
    value = request.headers.get(header)
    if not value:
        return None
    if scheme:
        prefix = scheme.lower() + " "
        if not value.lower().startswith(prefix):
            return None
        return value[len(prefix):].strip()
    return value.strip()


def require_token(valid, header="authorization", scheme="Bearer", exempt=()):
    """Build a before_request hook enforcing a token on every route."""
    if callable(valid):
        is_valid = valid
    else:
        accepted = set(valid)
        is_valid = lambda token: token in accepted  # noqa: E731

    exempt_paths = set(exempt)

    def hook(request):
        if request.path in exempt_paths or request.method == "OPTIONS":
            return None
        token = _extract_token(request, header, scheme)
        if token and is_valid(token):
            return None
        headers = []
        if scheme:
            headers.append(("www-authenticate", scheme))
        return Response.json({"error": "unauthorized"}, status=401, headers=headers)

    return hook


def _extract_basic(request):
    """Parse `Authorization: Basic <base64(user:pass)>` → (user, pass) or None.

    Tolerant of surrounding whitespace and a case-insensitive scheme;
    malformed base64, undecodable bytes, or a missing colon all yield None
    (→ 401 upstream), never an exception.
    """
    value = request.headers.get("authorization")
    if not value:
        return None
    parts = value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    try:
        raw = base64.b64decode(parts[1].strip().encode("ascii"), validate=True)
        decoded = raw.decode("utf-8")  # RFC 7617: UTF-8 credentials
    except Exception:  # noqa: BLE001 — any garbage is just "not credentials"
        return None
    username, sep, password = decoded.partition(":")
    if not sep:
        return None
    return username, password


def _dict_checker(users):
    """check(username, password) over {username: sha256_hexdigest | plaintext}.

    Scans every entry with constant-time comparisons on both username and
    password — no early exit, no timing signal for "user exists".
    """
    entries = [(str(u), str(v)) for u, v in users.items()]

    def check(username, password):
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        matched = False
        for stored_user, stored_secret in entries:
            user_ok = _ct_equal(username, stored_user)
            secret_ok = _ct_equal(digest, stored_secret) | _ct_equal(password, stored_secret)
            if user_ok and secret_ok:
                matched = True
        return matched

    return check


def require_basic(users, realm="pyre", exempt=()):
    """Build a before_request hook enforcing HTTP Basic auth (RFC 7617).

    `users` is a dict of {username: sha256_hexdigest_of_password} — store
    password HASHES, per the WS-C guardrail (plaintext values also work,
    for dev) — or a callable check(username, password) -> bool:

        import hashlib
        app.before_request(auth.require_basic(
            users={"alice": hashlib.sha256(b"s3cret").hexdigest()},
            realm="pyre", exempt=("/health",)))

    Failures answer 401 with `WWW-Authenticate: Basic realm="<realm>"`;
    OPTIONS preflights pass through. On success the username is attached
    as `request.user`.
    """
    check = users if callable(users) else _dict_checker(users)
    exempt_paths = set(exempt)
    challenge = 'Basic realm="%s"' % realm

    def hook(request):
        if request.path in exempt_paths or request.method == "OPTIONS":
            return None
        creds = _extract_basic(request)
        if creds is not None and check(creds[0], creds[1]):
            request.user = creds[0]
            return None
        return Response.json(
            {"error": "unauthorized"},
            status=401,
            headers=[("www-authenticate", challenge)],
        )

    return hook
