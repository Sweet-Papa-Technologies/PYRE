"""pyre.oidc — verify third-party OpenID Connect ID tokens in-canister.

The hard part of "log in with Google" on ICP is that the ID token is an
RS256-signed JWT and the canister has to verify that RSASSA-PKCS1-v1_5
signature *itself* — there is no trusted server to offload it to. RSA
*verification* is entropy-free and deterministic, so it rides the same
`_pyre_native` Rust-extension seam as pyre.crypto (RustCrypto `rsa` +
`p256`), with a host `cryptography` shim for `pyre dev` and unit tests.

    from pyre import oidc

    verifier = oidc.OidcVerifier(oidc.google(client_id="…apps.googleusercontent.com"))

    @app.post("/login", update=True)          # update: may outcall for JWKS
    async def login(req):
        claims = await verifier.verify(req.json()["id_token"])
        # claims["sub"], claims["email"], claims["email_verified"], claims["name"]
        session = issue_session(claims["sub"])   # your Phase-C session store
        return Response.json({"session": session})

WHY THIS IS CHEAP IN STEADY STATE — the amplification honesty note:
An HTTPS outcall fans out to ~13 nodes (the "13× tax"). If every login
refetched Google's JWKS, that tax would land on every login. It does not:
the JWKS is fetched ONCE per key-rotation and cached in a `pyre.data`
collection, so a steady-state login does ZERO outcalls — verification is
pure in-canister RSA math against the cached key. The only outcall is the
first login after a Google key rotation (unknown `kid` → refresh once).

WHAT THIS TRUSTS: the signature proves Google minted the token; the claim
checks (`iss`/`aud`/`exp`/`nbf`) prove it was minted FOR YOU and is still
valid. `aud` MUST equal your OAuth client id — skip it and any Google
token for any app would be accepted. The token is NOT a secret to hoard
(it is short-lived and bound to `aud`), but treat `email`/`sub` as
identity, not authorization.
"""

import json as _json

from pyre import data as _data
from pyre import ptime as _ptime
from pyre.compat import urllib_request as _urllib
from pyre.errors import PyreError

# Small allowance for clock skew between Google and the subnet (seconds).
DEFAULT_LEEWAY = 60

# JWKS documents are a few KB; cap the outcall response accordingly.
JWKS_MAX_RESPONSE_BYTES = 16_384

# Candid name of the JWKS-normalizing transform the canister must register
# (see transform_jwks_response below — the default header-only transform is
# NOT sufficient for JWKS endpoints).
JWKS_TRANSFORM = "pyre_oidc_jwks_transform"


class OidcError(PyreError):
    """Base class for every OIDC verification failure."""

    status = 401


class MalformedToken(OidcError):
    """The token is not a well-formed three-part base64url JWT."""


class UnsupportedAlgorithm(OidcError):
    """The token's `alg` header is not one we verify (RS256/ES256)."""


class UnknownSigningKey(OidcError):
    """No JWK matched the token's `kid`, even after a JWKS refresh."""


class InvalidSignature(OidcError):
    """The signature did not verify against the provider's public key."""


class InvalidClaims(OidcError):
    """A claim check failed: wrong issuer/audience, expired, or not-yet-valid."""


class JwksFetchError(OidcError):
    """The JWKS could not be fetched from the provider."""

    status = 502


# ---------------------------------------------------------------------------
# base64url + JWT decoding (pure Python — no external jwt library)
# ---------------------------------------------------------------------------

def _b64url_decode(segment):
    """Decode a base64url segment (no padding), returning bytes."""
    import base64

    if isinstance(segment, str):
        segment = segment.encode("ascii")
    pad = (-len(segment)) % 4
    try:
        return base64.urlsafe_b64decode(segment + b"=" * pad)
    except Exception as exc:  # noqa: BLE001 — any decode error is malformed
        raise MalformedToken("token segment is not valid base64url: %s" % exc)


def _b64url_uint(segment):
    """Decode a JWK base64url integer field (n/e/x/y) to big-endian bytes."""
    return _b64url_decode(segment)


def decode_jwt(id_token):
    """Split and decode a compact JWT without verifying it.

    Returns (header, payload, signing_input_bytes, signature_bytes) where
    header/payload are dicts, signing_input is the exact ASCII bytes that
    were signed ("<header>.<payload>"), and signature is the raw bytes.
    Raises MalformedToken on any structural problem.
    """
    if not isinstance(id_token, str):
        try:
            id_token = id_token.decode("ascii")
        except Exception:
            raise MalformedToken("id_token must be an ASCII compact JWT string")
    parts = id_token.split(".")
    if len(parts) != 3:
        raise MalformedToken(
            "compact JWT must have 3 dot-separated parts, got %d" % len(parts))
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = _json.loads(_b64url_decode(header_b64))
        payload = _json.loads(_b64url_decode(payload_b64))
    except (ValueError, MalformedToken) as exc:
        raise MalformedToken("JWT header/payload is not valid JSON: %s" % exc)
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise MalformedToken("JWT header and payload must be JSON objects")
    signing_input = (header_b64 + "." + payload_b64).encode("ascii")
    signature = _b64url_decode(signature_b64)
    return header, payload, signing_input, signature


# ---------------------------------------------------------------------------
# Providers — pluggable per §4 (google shipped, generic stubbed)
# ---------------------------------------------------------------------------

class Provider:
    """An OIDC provider description.

    issuer:    the exact `iss` value the token must carry.
    jwks_uri:  where to fetch the signing keys (JSON Web Key Set).
    audience:  your OAuth client id — the token's `aud` must equal this.
    name:      a short label for errors/logging.
    """

    def __init__(self, issuer, jwks_uri, audience, name=None):
        if not audience:
            raise ValueError(
                "OIDC audience (your OAuth client id) is required — without "
                "it any token minted for any app would be accepted")
        self.issuer = issuer
        self.jwks_uri = jwks_uri
        self.audience = audience
        self.name = name or issuer


def google(client_id):
    """Google's OIDC provider. `client_id` is your OAuth 2.0 Web client id
    ('…apps.googleusercontent.com') — public, not a secret. Google may set
    `iss` to either "accounts.google.com" or "https://accounts.google.com";
    both are accepted (see _issuer_ok)."""
    return Provider(
        issuer="https://accounts.google.com",
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
        audience=client_id,
        name="google",
    )


def generic(issuer, jwks_uri, client_id, name=None):
    """A stubbed second provider to prove pluggability (§4 acceptance).

    Point it at any standards-compliant OIDC issuer (GitHub Actions OIDC,
    Auth0, an in-house IdP, …): pass the issuer, its JWKS endpoint, and the
    audience your tokens are minted for. The verify path is identical to
    google() — only these three values change. This is intentionally NOT
    special-cased anywhere; adding a provider is data, not code.
    """
    return Provider(issuer=issuer, jwks_uri=jwks_uri, audience=client_id,
                    name=name or issuer)


# ---------------------------------------------------------------------------
# JWKS outcall determinism — the transform
# ---------------------------------------------------------------------------

def transform_jwks_response(response):
    """Canonicalize a JWKS HttpResponse so every replica agrees byte-for-byte.

    MEASURED FINDING (2026-07-03, the reason this exists): Google serves
    https://www.googleapis.com/oauth2/v3/certs from multiple backends that
    serialize the SAME key set with DIFFERENT JSON field ordering — 12
    consecutive fetches returned two byte-distinct bodies of identical
    logical content. On a 13-replica subnet each replica fetches
    independently, so the default header-only transform would let the
    replicas disagree and the outcall would intermittently fail consensus
    ON MAINNET while looking fine on a 1-node local replica.

    Normalization: strip volatile headers (same allowlist as the default
    transform), then parse the JSON body, sort the "keys" list by kid, and
    re-serialize with sorted object keys and canonical separators. A
    non-JSON body is passed through untouched (replicas will then disagree
    and the call fails loudly rather than silently).

    Canisters using pyre.oidc must register this under the name
    oidc.JWKS_TRANSFORM:

        from kybra import query
        from kybra.canisters.management import HttpResponse, HttpTransformArgs
        from pyre import oidc

        @query
        def pyre_oidc_jwks_transform(args: HttpTransformArgs) -> HttpResponse:
            return oidc.transform_jwks_response(args["response"])
    """
    from pyre.transform import transform_management_response

    resp = transform_management_response(response)
    try:
        doc = _json.loads(bytes(resp["body"]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return resp  # not JSON: nothing safe to normalize
    if isinstance(doc, dict) and isinstance(doc.get("keys"), list):
        doc["keys"] = sorted(
            (k for k in doc["keys"] if isinstance(k, dict)),
            key=lambda k: str(k.get("kid", "")),
        )
    resp["body"] = _json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return resp


# ---------------------------------------------------------------------------
# JWKS cache (pyre.data) — the piece that collapses the 13× outcall tax
# ---------------------------------------------------------------------------

class _JwksCache:
    """One `pyre.data` record per provider issuer, holding its live keys.

    A cache hit means a login costs ZERO outcalls. On a `kid` miss we
    refetch once (Google rotates keys), replacing the record.
    """

    def __init__(self):
        self._col = _data.collection("pyre_oidc_jwks")

    def _record(self, issuer):
        page = self._col.list(limit=1, where={"issuer": issuer})
        items = page["items"]
        return items[0] if items else None

    def get_keys(self, issuer):
        rec = self._record(issuer)
        return rec["keys"] if rec else None

    def store(self, issuer, keys):
        doc = {"issuer": issuer, "keys": keys, "fetched_ns": _ptime.now_ns()}
        existing = self._record(issuer)
        if existing is not None:
            self._col.replace(existing["id"], doc)
        else:
            self._col.insert(doc)


# ---------------------------------------------------------------------------
# Signature backends: _pyre_native in-canister, `cryptography` on host
# ---------------------------------------------------------------------------

def _native():
    try:
        import _pyre_native
        return _pyre_native
    except ImportError:
        return None


_SIG_UNAVAILABLE_HOST = (
    "OIDC signature verification on host CPython needs the 'cryptography' "
    "package: pip install cryptography (dev-only shim — in-canister the "
    "backend is the _pyre_native Rust extension). ")


def _verify_rs256(jwk, signing_input, signature):
    n = _b64url_uint(jwk["n"])
    e = _b64url_uint(jwk["e"])
    native = _native()
    if native is not None:
        return bool(native.rsa_pkcs1v15_verify_sha256(n, e, signing_input, signature))
    return _host_verify_rs256(n, e, signing_input, signature)


def _verify_es256(jwk, signing_input, signature):
    x = _b64url_uint(jwk["x"])
    y = _b64url_uint(jwk["y"])
    if len(x) != 32 or len(y) != 32:
        raise InvalidSignature("ES256 JWK x/y must decode to 32 bytes each")
    if len(signature) != 64:
        raise InvalidSignature("ES256 signature must be 64 bytes (r||s)")
    native = _native()
    if native is not None:
        return bool(native.ecdsa_p256_verify_sha256(x, y, signing_input, signature))
    return _host_verify_es256(x, y, signing_input, signature)


def _host_verify_rs256(n, e, signing_input, signature):
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.exceptions import InvalidSignature as _CryptoInvalidSig
    except ImportError:
        raise OidcError(_SIG_UNAVAILABLE_HOST)
    pub = rsa.RSAPublicNumbers(
        int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
    try:
        pub.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        return True
    except _CryptoInvalidSig:
        return False


def _host_verify_es256(x, y, signing_input, signature):
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.exceptions import InvalidSignature as _CryptoInvalidSig
    except ImportError:
        raise OidcError(_SIG_UNAVAILABLE_HOST)
    pub = ec.EllipticCurvePublicNumbers(
        int.from_bytes(x, "big"), int.from_bytes(y, "big"),
        ec.SECP256R1()).public_key()
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    der = utils.encode_dss_signature(r, s)
    try:
        pub.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
        return True
    except _CryptoInvalidSig:
        return False


_ALG_VERIFIERS = {
    "RS256": _verify_rs256,
    "ES256": _verify_es256,
}


# ---------------------------------------------------------------------------
# The verifier
# ---------------------------------------------------------------------------

class OidcVerifier:
    """Verify ID tokens from one OIDC provider.

    verify(id_token) is awaitable in async handlers and yieldable in
    generator handlers (it may perform a JWKS outcall on a `kid` miss).
    """

    def __init__(self, provider, leeway=DEFAULT_LEEWAY, jwks_transform=JWKS_TRANSFORM):
        """jwks_transform: Candid name of the transform query the canister
        registers for JWKS fetches. Defaults to oidc.JWKS_TRANSFORM (the
        normalizing transform — see transform_jwks_response; JWKS bodies
        are NOT byte-stable across Google's backends, so the header-only
        default transform is unsafe on a multi-replica subnet)."""
        self.provider = provider
        self.leeway = int(leeway)
        self.jwks_transform = jwks_transform
        self._cache = _JwksCache()

    # -- public API ---------------------------------------------------------

    def verify(self, id_token):
        """Return the verified claims dict, or raise an OidcError subclass."""
        return _AwaitableOp(self._verify_gen(id_token))

    # -- the generator that drives outcalls ---------------------------------

    def _verify_gen(self, id_token):
        header, payload, signing_input, signature = decode_jwt(id_token)
        alg = header.get("alg")
        verifier = _ALG_VERIFIERS.get(alg)
        if verifier is None:
            raise UnsupportedAlgorithm(
                "unsupported JWT alg %r (this verifier handles %s)"
                % (alg, "/".join(sorted(_ALG_VERIFIERS))))
        kid = header.get("kid")

        jwk = self._find_key(kid, alg)
        refreshed = False
        if jwk is None:
            keys = yield from self._fetch_jwks()
            self._cache.store(self.provider.issuer, keys)
            refreshed = True
            jwk = self._find_key(kid, alg)
        if jwk is None:
            raise UnknownSigningKey(
                "no JWK matched kid=%r for provider %s%s"
                % (kid, self.provider.name,
                   " even after a JWKS refresh" if refreshed else ""))

        if not verifier(jwk, signing_input, signature):
            raise InvalidSignature(
                "%s signature verification failed for provider %s"
                % (alg, self.provider.name))

        self._validate_claims(payload)
        return payload

    # -- key selection ------------------------------------------------------

    def _find_key(self, kid, alg):
        keys = self._cache.get_keys(self.provider.issuer)
        if not keys:
            return None
        want_kty = "RSA" if alg == "RS256" else "EC"
        candidates = [k for k in keys if k.get("kty") == want_kty]
        if kid is not None:
            for k in candidates:
                if k.get("kid") == kid:
                    return k
            return None
        # No kid in the token header: only unambiguous if exactly one key.
        return candidates[0] if len(candidates) == 1 else None

    def _fetch_jwks(self):
        try:
            resp = yield _urllib.urlopen(
                self.provider.jwks_uri,
                max_response_bytes=JWKS_MAX_RESPONSE_BYTES,
                transform=self.jwks_transform,
            )
        except PyreError as exc:
            raise JwksFetchError(
                "could not fetch JWKS for %s from %s: %s"
                % (self.provider.name, self.provider.jwks_uri, exc))
        if resp.status != 200:
            raise JwksFetchError(
                "JWKS endpoint %s returned HTTP %d"
                % (self.provider.jwks_uri, resp.status))
        try:
            doc = resp.json()
            keys = doc["keys"]
        except (ValueError, KeyError, TypeError) as exc:
            raise JwksFetchError(
                "JWKS from %s is not a valid key set: %s"
                % (self.provider.jwks_uri, exc))
        if not isinstance(keys, list) or not keys:
            raise JwksFetchError("JWKS from %s has no keys" % self.provider.jwks_uri)
        return keys

    # -- claim validation ---------------------------------------------------

    def _validate_claims(self, payload):
        p = self.provider
        if not _issuer_ok(payload.get("iss"), p.issuer):
            raise InvalidClaims(
                "issuer mismatch: token iss=%r, expected %r"
                % (payload.get("iss"), p.issuer))
        if not _audience_ok(payload.get("aud"), p.audience):
            raise InvalidClaims(
                "audience mismatch: token aud=%r is not this client id"
                % (payload.get("aud"),))

        now = _ptime.now()
        exp = payload.get("exp")
        if exp is None:
            raise InvalidClaims("token has no exp claim")
        if now > int(exp) + self.leeway:
            raise InvalidClaims("token expired (exp=%s, now=%s)" % (exp, now))
        nbf = payload.get("nbf")
        if nbf is not None and now + self.leeway < int(nbf):
            raise InvalidClaims("token not yet valid (nbf=%s, now=%s)" % (nbf, now))
        iat = payload.get("iat")
        if iat is not None and now + self.leeway < int(iat):
            raise InvalidClaims("token issued in the future (iat=%s, now=%s)" % (iat, now))


def _issuer_ok(token_iss, expected):
    """Google mints `iss` as both "accounts.google.com" and the https form;
    accept either against a configured https issuer, exact match otherwise."""
    if token_iss == expected:
        return True
    if expected == "https://accounts.google.com":
        return token_iss == "accounts.google.com"
    return False


def _audience_ok(token_aud, expected):
    """`aud` may be a string or (per spec) a list of audiences."""
    if isinstance(token_aud, str):
        return token_aud == expected
    if isinstance(token_aud, (list, tuple)):
        return expected in token_aud
    return False


class _AwaitableOp:
    """Awaitable/yieldable wrapper over a generator that yields futures
    (mirrors pyre.sign._AwaitableOp so verify() works under both the
    canister pump and the dev/test pump_sync)."""

    def __init__(self, gen):
        self._gen = gen

    def __await__(self):
        return self._gen

    def __iter__(self):
        return self._gen
