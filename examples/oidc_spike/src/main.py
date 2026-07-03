"""PYRE PyreBlog Phase-B GATE spike canister.

Proves, IN-CANISTER, the linchpin of "log in with Google" on ICP:

  1. verify_kat()          RS256 + ES256 signature verification straight
                           through the _pyre_native Rust extension
                           (RustCrypto rsa/p256), with tamper/wrong-message
                           negative controls.
  2. verify_end_to_end()   the FULL pyre.oidc.OidcVerifier path -- decode
                           JWT, select JWK from the pyre.data cache,
                           verify RS256/ES256, validate iss/aud/exp -- against
                           a seeded JWKS, i.e. the steady-state ZERO-OUTCALL
                           login. Negative controls: expired, wrong-aud,
                           tampered-signature all rejected.
  3. jwks_fetch()          a REAL HTTPS outcall to Google's live JWKS
                           endpoint, proving the fetch+cache leg.
  4. verify_live_google()  verify a REAL Google ID token end-to-end.

Build/deploy:  scripts/build_native.sh oidc_spike --install
"""

from kybra import StableBTreeMap, ic, nat64, query, update
from kybra.canisters.management import HttpResponse, HttpTransformArgs

import pyre.kv
from pyre import oidc
from pyre.outcall import pump, pump_sync
from pyre.transform import transform_management_response

pyre_kv_store = StableBTreeMap[str, str](
    memory_id=250, max_key_size=1024, max_value_size=64000)
pyre.kv.bind_backend(pyre_kv_store)


@query
def pyre_default_transform(args: HttpTransformArgs) -> HttpResponse:
    return transform_management_response(args["response"])


@query
def pyre_oidc_jwks_transform(args: HttpTransformArgs) -> HttpResponse:
    """JWKS-normalizing transform (oidc.JWKS_TRANSFORM): Google serves the
    same key set with per-backend JSON field ordering, so replicas must
    canonicalize the body or mainnet consensus intermittently fails."""
    return oidc.transform_jwks_response(args["response"])


RS_N = bytes.fromhex("91d93f59f60992deb1253410966e893ec363444c46cf54f72528496c89a6a1320d286b5b1142503b85174eab526cd578dfffc0a2f30434331703c2404d2370a13ccd021154df9756b55d6317af6ba2ed020133ce3c0daacbadfa271f08f9478a1d4173fbc0c64f0bfea7602ed60befaece38f49f0b26bd4b3e4f3a84b89a09393f2aa3237c9090d33bcff5e85efca2eb16c6cfeba149f336394d0c519d610f5d3cfbd183db0f3044d24ad403f35c853f5a48afcde707156689dcba8a9a22f5d8e9fc465aec9733057758e4ea77b21ff4ba081599d37b76b1da80f0fcb7bf7c9d736cb700eebafa3842b0b0ff97241c19ec3a37873dfe117594017aeb1eba8407")
RS_E = bytes.fromhex("010001")
RS_MSG = b"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJweXJlLW9pZGMta2F0In0"
RS_SIG = bytes.fromhex("026d90bcb638c0a721ef7fb8ef42d258fc4be0c37b14f9e21faf7e1578234036545e590e5ec2771e07680197b7e1b00ad6d3f98fea8661823503de16d019121cc7ab9d05d24dcf360ffbd0aa8644969d57cc41854af6fbe26d83a878ddf3c35588a29577fd9e7a56c169f535c2d2ad71ac4b246a733ee43b1096f358f4f41941fc709baa5bf9d7dc5fb983b974d2459e976a3670bded7040fdfa7ed2a9c5274736f73c9a0de5cce0cbbfff464cbeba76ac9e002ca7ebbdeee7c95788e49907b47b1360f661a7e43ab815295c065659ab2348b463df222131a72a3789dafcc0615c82ab967645863170a3e4b18b0666a3de09b5320e487e03bb56b37454168c84")
ES_X = bytes.fromhex("1f6810051ed1c9d5d6424be0138fb81530e2d70a11018d1af36edbe809d62b0e")
ES_Y = bytes.fromhex("035895780813c008d6a6e1720bcc44001df0b3b88e53ec4607569b5a90531516")
ES_SIG = bytes.fromhex("f2334ff25011ced63018ceb1561dc1eb05ef6a14327bab5dbf20e8ab6439ac5d112107cab27b362292d44de4270fd10d8d0820f1291374335a8d1f3d882d7243")

ISS = "https://accounts.google.com"
AUD = "pyre-blog-test.apps.googleusercontent.com"
JWK_RSA = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": "pyrekat1", "n": "rkd7tOYR0D_QciT7Xyp5GDOhn7tQBERFtnip0fdjtmm7sI4L7A5h93MDpfntN0lWvrvj723Rg7Vnos6ZYRrlpj0JIIA9WPWpL9fMiBuUFFkdsSCqfGzf9q7liBPWee3iQ06AcP0WkgRUiCTfqOxnUsmA73IPqWFb_UQ0ntqe3OT3zaFW2vi9RSryFdjiU1oi2f0RhO1A24Toy2rOYhDpAwL3YhBNLWtt64qLNZYQddGtydYQC1Q9Mq7fZULwjs2KQAlipHLPb0gmFIshnMxOy6ENBh-ZvIYwDPPOuO_L-TxdfmGo__rQhShh2cX49BTYBfRhiCSfwk2W3LNRJ2rxEw", "e": "AQAB"}
JWK_EC = {"kty": "EC", "use": "sig", "alg": "ES256", "kid": "eckat1", "crv": "P-256", "x": "uoumYMxQ97IeqXmNPI4idNhE8jMat93DOkFz0MgM8BA", "y": "Q-pzDXdqOgks_TcZUTcwToIzLLk1oVjDvzozp8vSTBE"}
TOKEN_VALID = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InB5cmVrYXQxIn0.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhdWQiOiJweXJlLWJsb2ctdGVzdC5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbSIsInN1YiI6IjEwODEwMGRpZ2l0cyIsImVtYWlsIjoicmVhZGVyQGV4YW1wbGUuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5hbWUiOiJUZXN0IFJlYWRlciIsImlhdCI6MTAwMDAwMDAwMCwiZXhwIjo0MTAyNDQ0ODAwfQ.VOvUJ0mMt30TdAzo-uhT-xKm49rUEtzN0dWHwSSaejtiL81qQInwLALjhZoUXj-poD6MHivhjUrVcTG7oVJfeOmj_w4D-HjXjrgo0S-6gvyumpoeb1hrcmHZSaR-C1ozUnHTsZuY0ISIdeUgxL2LdRLNSKfAQ2oMIIsLWluY9hBI31qFBWKe_dmoLPrF42SOOfI-247Y1Wf2ri6Gh2QLlPAN3Hqea-dre7ZsKO9WDg0GkNHlyyQ70Z92IpK1kTdsgOB-Ttd5duHCWO7rFsP-BdPbTrChIiezq4uXF72aIYhSV6z40ujZJNUjp1iecOmgSkLPLdWUYyqJsSYVrApCFw"
TOKEN_EXPIRED = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InB5cmVrYXQxIn0.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhdWQiOiJweXJlLWJsb2ctdGVzdC5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbSIsInN1YiI6IjEwODEwMGRpZ2l0cyIsImVtYWlsIjoicmVhZGVyQGV4YW1wbGUuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5hbWUiOiJUZXN0IFJlYWRlciIsImlhdCI6MTAwMDAwMDAwMCwiZXhwIjoxMjYyMzA0MDAwfQ.T5y8SjlOzjCIItNPGD-aZCN9-5tnb-y3l7bF-okQvSF2daT-jTt_aIIaAOVwaj52a7VICv2hh221MnRXRMEe7t4CLaiT5_DGmSnGsJgIp9fhiO9LuiREAl0SxzooLhSunCD-9zPSUYCYfYrmBqUNcMQ7smCH7coe3UJv46HWqMX-qC9cOD9PxUslUNuVoG7Dc8tDkT5cNzUC7zv-4r17Jg5GghZFj6wqPr_g68Lj4mMu3BOxoOSuP2FnOwt55qDL18KY7cgEtUlv5O-yWoeuBMqhDPqZKOBhGY2irotWzbEFilil4uARwKXxpLarX9ahx9MSMn6QE4w76n24ei_taw"
TOKEN_WRONGAUD = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InB5cmVrYXQxIn0.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhdWQiOiJzb21lb25lLWVsc2UuYXBwcy5nb29nbGV1c2VyY29udGVudC5jb20iLCJzdWIiOiIxMDgxMDBkaWdpdHMiLCJlbWFpbCI6InJlYWRlckBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiVGVzdCBSZWFkZXIiLCJpYXQiOjEwMDAwMDAwMDAsImV4cCI6NDEwMjQ0NDgwMH0.NjExUt0WyjoXuqcFgtpWZ3ZKorH741tvcs8uzWiCC76Udqi3WYlHothymTlJ4DV6yixdGW2BmmW7rWatORe57c2cdCZCc3jOD6DXLHvCIioa3CzcZVbx_ZMZUhsdYGoiza30QYRveL3HfXSp29w6Akb_E-it_wWYAX8hD6li7EJmmXErdVgXLLcYxGnPR33d0e5otVXPmxEpllqhTRNhjp-n--jRoTgDquh1l8pFIbXER0usfk2XkIYTfkuYjTm4N1JzP58mtaVKQDaeVPDnTqOxeWmh0p05d-gX4BzERRqTzYr1-J-Nq7k0xrBZPOrd6tWGvIHZEKGRfZCBl0KoFA"
TOKEN_TAMPERED = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InB5cmVrYXQxIn0.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhdWQiOiJweXJlLWJsb2ctdGVzdC5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbSIsInN1YiI6IjEwODEwMGRpZ2l0cyIsImVtYWlsIjoicmVhZGVyQGV4YW1wbGUuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5hbWUiOiJUZXN0IFJlYWRlciIsImlhdCI6MTAwMDAwMDAwMCwiZXhwIjo0MTAyNDQ0ODAwfQ.VOvUJ0mMt30TdAzo-uhT-xKm49rUEtzN0dWHwSSaejtiL81qQInwLALjhZoUXj-poD6MHivhjUrVcTG7oVJfeOmj_w4D-HjXjrgo0S-6gvyumpoeb1hrcmHZSaR-C1ozUnHTsZuY0ISIdeUgxL2LdRLNSKfAQ2oMIIsLWluY9hBI31qFBWKe_dmoLPrF42SOOfI-247Y1Wf2ri6Gh2QLlPAN3Hqea-dre7ZsKO9WDg0GkNHlyyQ70Z92IpK1kTdsgOB-Ttd5duHCWO7rFsP-BdPbTrChIiezq4uXF72aIYhSV6z40ujZJNUjp1iecOmgSkLPLdWUYyqJsSYVrApAFw"
TOKEN_ES_VALID = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImVja2F0MSJ9.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhdWQiOiJweXJlLWJsb2ctdGVzdC5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbSIsInN1YiI6IjEwODEwMGRpZ2l0cyIsImVtYWlsIjoicmVhZGVyQGV4YW1wbGUuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5hbWUiOiJUZXN0IFJlYWRlciIsImlhdCI6MTAwMDAwMDAwMCwiZXhwIjo0MTAyNDQ0ODAwfQ.4y0kr2FbWRAWPRMzf6kkQXaBcn6WoGm95vbaAyVbeRy9xd8c-0fXieWntl_SGpWq0Zwwt94Ab5b-kRvyNR84Pg"


@query
def native_present() -> str:
    try:
        import _pyre_native  # noqa: F401
        return "yes"
    except ImportError:
        return "no"


@query
def verify_kat() -> str:
    import _pyre_native as nat
    p = []
    p.append("rs256.valid=" + ok(nat.rsa_pkcs1v15_verify_sha256(RS_N, RS_E, RS_MSG, RS_SIG)))
    bad = bytearray(RS_SIG); bad[0] ^= 1
    p.append("rs256.tampered_rejected=" + ok(not nat.rsa_pkcs1v15_verify_sha256(RS_N, RS_E, RS_MSG, bytes(bad))))
    p.append("rs256.wrong_msg_rejected=" + ok(not nat.rsa_pkcs1v15_verify_sha256(RS_N, RS_E, RS_MSG + b"x", RS_SIG)))
    p.append("es256.valid=" + ok(nat.ecdsa_p256_verify_sha256(ES_X, ES_Y, RS_MSG, ES_SIG)))
    eb = bytearray(ES_SIG); eb[0] ^= 1
    p.append("es256.tampered_rejected=" + ok(not nat.ecdsa_p256_verify_sha256(ES_X, ES_Y, RS_MSG, bytes(eb))))
    return ";".join(p)


def ok(b):
    return "ok" if b else "FAIL"


def _no_outcall(_fut):
    raise AssertionError("cache HIT must perform ZERO outcalls")


def _hit(op):
    return pump_sync(iter(op), _no_outcall)


@update
def verify_end_to_end() -> str:
    oidc._JwksCache().store(ISS, [JWK_RSA, JWK_EC])
    prov = oidc.generic(issuer=ISS, jwks_uri="https://unused.example/certs",
                        client_id=AUD, name="google")
    v = oidc.OidcVerifier(prov)
    p = []
    try:
        c = _hit(v.verify(TOKEN_VALID))
        p.append("valid_rs256=" + ok(c.get("sub") == "108100digits" and c.get("email_verified") is True))
    except Exception as e:  # noqa: BLE001
        p.append("valid_rs256=FAIL:" + str(e))
    try:
        c = _hit(v.verify(TOKEN_ES_VALID))
        p.append("valid_es256=" + ok(c.get("sub") == "108100digits"))
    except Exception as e:  # noqa: BLE001
        p.append("valid_es256=FAIL:" + str(e))
    p.append("expired_rejected=" + _expect(v, TOKEN_EXPIRED, oidc.InvalidClaims))
    p.append("wrongaud_rejected=" + _expect(v, TOKEN_WRONGAUD, oidc.InvalidClaims))
    p.append("tampered_rejected=" + _expect(v, TOKEN_TAMPERED, oidc.InvalidSignature))
    return ";".join(p)


def _expect(v, token, exc_type):
    try:
        _hit(v.verify(token))
        return "FAIL-accepted"
    except exc_type:
        return "ok"
    except Exception as e:  # noqa: BLE001
        return "FAIL-wrongerr:" + type(e).__name__


@update
def jwks_fetch() -> str:
    return (yield from pump(_jwks_fetch_gen()))


def _jwks_fetch_gen():
    from pyre.compat import urllib_request as urllib
    resp = yield urllib.urlopen(
        "https://www.googleapis.com/oauth2/v3/certs", max_response_bytes=8192,
        transform=oidc.JWKS_TRANSFORM)
    data = resp.json()
    keys = data.get("keys", [])
    kids = ",".join(k.get("kid", "?")[:8] for k in keys)
    return "status=" + str(resp.status) + ";keys=" + str(len(keys)) + ";kids=" + kids


@update
def verify_live_google(id_token: str) -> str:
    return (yield from pump(_verify_live_gen(id_token)))


def _verify_live_gen(id_token):
    v = oidc.OidcVerifier(oidc.google(client_id=AUD))
    try:
        c = yield from v.verify(id_token)
        return "ok:sub=" + str(c.get("sub")) + ";email=" + str(c.get("email"))
    except oidc.OidcError as e:
        return "rejected:" + type(e).__name__ + ":" + str(e)


# --- gate instrumentation (Phase-B measurements + the paste-a-token path) ----
#
# PASTE A REAL GOOGLE TOKEN (30 seconds, no app registration):
#   1. open https://developers.google.com/oauthplayground
#   2. authorize "Google OAuth2 API v2" -> openid + email scopes
#   3. "Exchange authorization code for tokens", copy `id_token`
#   4. dfx canister call oidc_spike verify_token \
#        '("<id_token>", "407408718192.apps.googleusercontent.com")'
#      (that audience is the OAuth Playground's own client id, which such
#       tokens carry as `aud`).


@update
def verify_token(token: str, audience: str) -> str:
    """Full pyre.oidc verify with a caller-chosen audience: cached Google
    JWKS, refresh-on-kid-miss outcall, signature + claims checks."""
    return (yield from pump(_verify_token_gen(token, audience)))


def _verify_token_gen(token, audience):
    v = oidc.OidcVerifier(oidc.google(client_id=audience))
    try:
        import json
        c = yield from v.verify(token)
        return "OK " + json.dumps(c, sort_keys=True)
    except oidc.OidcError as e:
        return "REJECT " + type(e).__name__ + ": " + str(e)


def _query_no_outcall(_fut):
    raise oidc.JwksFetchError(
        "kid not in the cached JWKS and a query cannot outcall; "
        "call the update method verify_token first")


@query
def verify_token_cached(token: str, audience: str) -> str:
    """The steady-state login check: SYNC verify against the cached JWKS —
    ZERO outcalls, query-fast (spec §6: caching collapses the 13x tax)."""
    import json
    v = oidc.OidcVerifier(oidc.google(client_id=audience))
    try:
        c = pump_sync(iter(v.verify(token)), _query_no_outcall)
        return "OK " + json.dumps(c, sort_keys=True)
    except oidc.OidcError as e:
        return "REJECT " + type(e).__name__ + ": " + str(e)


@update
def inject_test_jwk(jwk_json: str) -> str:
    """GATE HARNESS: merge a host-minted public JWK ALONGSIDE the cached
    REAL Google keys (fetching them first if the cache is empty), so a
    token we can actually sign verifies against a cache that also holds
    real Google key material — Google will not sign for a headless test."""
    return (yield from pump(_inject_gen(jwk_json)))


def _inject_gen(jwk_json):
    import json
    cache = oidc._JwksCache()
    keys = cache.get_keys(ISS)
    if keys is None:
        keys = yield from oidc.OidcVerifier(oidc.google(client_id=AUD))._fetch_jwks()
    jwk = json.loads(jwk_json)
    keys = [k for k in keys if k.get("kid") != jwk.get("kid")] + [jwk]
    cache.store(ISS, keys)
    return "cached_keys=" + str(len(keys)) + ";kids=" + ",".join(
        k.get("kid", "?")[:12] for k in keys)


@query
def cached_kids() -> str:
    """Which kids the JWKS cache holds right now (survives upgrades: the
    cache rides pyre.kv -> StableBTreeMap)."""
    keys = oidc._JwksCache().get_keys(ISS)
    if keys is None:
        return "none"
    return ",".join(k.get("kid", "?")[:12] for k in keys)


@update
def jwks_fetch_hash() -> str:
    """sha256 of the raw JWKS body — call twice and diff to observe
    upstream body stability (the outcall-determinism question)."""
    return (yield from pump(_jwks_hash_gen()))


def _jwks_hash_gen():
    import hashlib
    from pyre.compat import urllib_request as urllib
    resp = yield urllib.urlopen(
        "https://www.googleapis.com/oauth2/v3/certs",
        max_response_bytes=16384,
        transform=oidc.JWKS_TRANSFORM,  # canonicalized: replicas must agree
    )
    body = resp.read()
    return ("status=" + str(resp.status) + ";bytes=" + str(len(body))
            + ";sha256=" + hashlib.sha256(body).hexdigest())


@query
def perf_baseline() -> nat64:
    """Empty-query instruction floor (interpreter dispatch overhead)."""
    return ic.performance_counter(0)


@query
def perf_native_rs256() -> nat64:
    """Instructions for ONE raw native RS256 verify (KAT vector) — isolates
    the Rust signature check from the Python JWT plumbing."""
    import _pyre_native as nat
    nat.rsa_pkcs1v15_verify_sha256(RS_N, RS_E, RS_MSG, RS_SIG)
    return ic.performance_counter(0)


@query
def perf_verify_cached(token: str, audience: str) -> nat64:
    """Instructions for ONE full cached-path verify (decode + JWK select +
    RS256 + claims). Subtract perf_baseline for the per-verify cost."""
    v = oidc.OidcVerifier(oidc.google(client_id=audience))
    try:
        pump_sync(iter(v.verify(token)), _query_no_outcall)
    except oidc.OidcError:
        pass  # a rejected token costs about the same; we want the counter
    return ic.performance_counter(0)
