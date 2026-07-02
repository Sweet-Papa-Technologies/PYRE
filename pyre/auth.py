"""Basic auth middleware (WS-C): bearer / API-key checks as a before-hook.

    from pyre import auth

    app.before_request(auth.require_token(
        valid={"dev-token-1"},              # a set of tokens, or a callable
        exempt=("/health",),                # paths that stay open
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

from pyre.http_types import Response


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
