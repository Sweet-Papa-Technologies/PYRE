"""pyre.oidc — OIDC ID-token verification (PyreBlog Phase B gate).

Tokens are minted on the host with `cryptography` (RS256 + ES256), so the
verify path under test is exactly what a canister sees: a compact JWS from
an issuer whose public keys arrive as a JWKS. The JWKS outcall is faked
through pump_sync, mirroring tests/unit/test_outcall.py.
"""

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec as _ec
from cryptography.hazmat.primitives.asymmetric import padding as _padding
from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from pyre import kv, oidc
from pyre._runtime import ctx
from pyre.errors import OutcallFailed
from pyre.outcall import pump_sync

CLIENT_ID = "12345-test.apps.googleusercontent.com"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# Module-level keys: generating RSA keys per-test would dominate runtime.
RSA_KEY = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA_KEY_2 = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_KEY = _ec.generate_private_key(_ec.SECP256R1())


@pytest.fixture(autouse=True)
def clean_store():
    """pyre.oidc caches JWKS in pyre.data -> pyre.kv; isolate each test."""
    ctx.in_query = False
    for key in list(kv.keys()):
        kv.delete(key)
    yield
    ctx.in_query = False


# ---------------------------------------------------------------------------
# minting helpers
# ---------------------------------------------------------------------------

def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def int_bytes(value, length=None):
    return value.to_bytes(length or (value.bit_length() + 7) // 8, "big")


def rsa_jwk(kid="test-rsa", key=None):
    pub = (key or RSA_KEY).public_key().public_numbers()
    return {
        "kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid,
        "n": b64u(int_bytes(pub.n)), "e": b64u(int_bytes(pub.e)),
    }


def ec_jwk(kid="test-ec"):
    pub = EC_KEY.public_key().public_numbers()
    return {
        "kty": "EC", "crv": "P-256", "use": "sig", "kid": kid,
        "x": b64u(int_bytes(pub.x, 32)), "y": b64u(int_bytes(pub.y, 32)),
    }


def base_claims(**over):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1093026273226180000001",
        "email": "reader@example.com",
        "iat": now - 10,
        "exp": now + 3600,
    }
    claims.update(over)
    return claims


def mint(claims, *, alg="RS256", kid="test-rsa", rsa_key=None, header_extra=None):
    header = {"alg": alg, "typ": "JWT"}
    if kid is not None:
        header["kid"] = kid
    if header_extra:
        header.update(header_extra)
    signing_input = "%s.%s" % (
        b64u(json.dumps(header).encode()), b64u(json.dumps(claims).encode()))
    if alg == "RS256":
        sig = (rsa_key or RSA_KEY).sign(
            signing_input.encode("ascii"), _padding.PKCS1v15(), hashes.SHA256())
    elif alg == "ES256":
        der = EC_KEY.sign(signing_input.encode("ascii"), _ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        sig = int_bytes(r, 32) + int_bytes(s, 32)
    else:  # unsigned / bogus alg — verifier must reject before sig checks
        sig = b"not-a-signature"
    return "%s.%s" % (signing_input, b64u(sig))


# ---------------------------------------------------------------------------
# pump plumbing (mirrors test_outcall.py)
# ---------------------------------------------------------------------------

def jwks_response(fut, jwks):
    return fut._wrap_response({
        "status": 200,
        "headers": [{"name": "content-type", "value": "application/json"}],
        "body": json.dumps(jwks).encode("utf-8"),
    })


def make_resolver(jwks, calls=None, status=200, body=None):
    def resolve(fut):
        if calls is not None:
            calls.append(fut.url)
        if status != 200 or body is not None:
            return fut._wrap_response({
                "status": status, "headers": [], "body": body or b""})
        return jwks_response(fut, jwks)
    return resolve


def no_outcall(fut):
    raise AssertionError("unexpected JWKS outcall to %s" % fut.url)


def drive(op, resolve=no_outcall):
    """Run an OidcVerifier.verify() awaitable to completion."""
    return pump_sync(iter(op), resolve)


def make_verifier(provider=None, **kwargs):
    provider = provider or oidc.google(client_id=CLIENT_ID)
    return oidc.OidcVerifier(provider, **kwargs)


# ---------------------------------------------------------------------------
# golden paths
# ---------------------------------------------------------------------------

def test_rs256_golden_path_fetches_jwks_once():
    calls = []
    verifier = make_verifier()
    claims = drive(verifier.verify(mint(base_claims())),
                   make_resolver({"keys": [rsa_jwk()]}, calls))
    assert claims["sub"] == "1093026273226180000001"
    assert claims["email"] == "reader@example.com"
    assert calls == [GOOGLE_JWKS_URL]


def test_cached_jwks_means_zero_outcalls_on_second_login():
    verifier = make_verifier()
    drive(verifier.verify(mint(base_claims())),
          make_resolver({"keys": [rsa_jwk()]}))
    # Steady state (§6): the cache collapses the 13x amplification tax.
    claims = drive(verifier.verify(mint(base_claims())), no_outcall)
    assert claims["aud"] == CLIENT_ID


def test_jwks_cache_is_shared_across_verifier_instances():
    drive(make_verifier().verify(mint(base_claims())),
          make_resolver({"keys": [rsa_jwk()]}))
    # New verifier, same pyre.data-backed cache: still zero outcalls.
    claims = drive(make_verifier().verify(mint(base_claims())), no_outcall)
    assert claims["iss"] == "https://accounts.google.com"


def test_es256_golden_path():
    verifier = make_verifier()
    claims = drive(verifier.verify(mint(base_claims(), alg="ES256", kid="test-ec")),
                   make_resolver({"keys": [ec_jwk()]}))
    assert claims["sub"]


def test_mixed_jwks_selects_key_by_kid_and_kty():
    jwks = {"keys": [ec_jwk(), rsa_jwk(), rsa_jwk(kid="other", key=RSA_KEY_2)]}
    verifier = make_verifier()
    assert drive(verifier.verify(mint(base_claims())), make_resolver(jwks))
    assert drive(verifier.verify(
        mint(base_claims(), alg="ES256", kid="test-ec")), no_outcall)


def test_no_kid_header_allowed_when_jwks_is_unambiguous():
    verifier = make_verifier()
    claims = drive(verifier.verify(mint(base_claims(), kid=None)),
                   make_resolver({"keys": [rsa_jwk()]}))
    assert claims["sub"]


def test_iss_short_form_accepted_for_google():
    verifier = make_verifier()
    claims = drive(verifier.verify(mint(base_claims(iss="accounts.google.com"))),
                   make_resolver({"keys": [rsa_jwk()]}))
    assert claims["iss"] == "accounts.google.com"


def test_aud_as_list_containing_client_id():
    verifier = make_verifier()
    claims = drive(
        verifier.verify(mint(base_claims(aud=[CLIENT_ID, "other-client"]))),
        make_resolver({"keys": [rsa_jwk()]}))
    assert CLIENT_ID in claims["aud"]


def test_exp_within_leeway_passes():
    verifier = make_verifier()
    token = mint(base_claims(exp=int(time.time()) - 30))  # expired 30s < 60s leeway
    assert drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


# ---------------------------------------------------------------------------
# rejection paths
# ---------------------------------------------------------------------------

def preload(verifier, jwks):
    """Warm the JWKS cache through the public verify path."""
    drive(verifier.verify(mint(base_claims())),
          make_resolver({"keys": jwks["keys"] + [rsa_jwk()]})
          if "test-rsa" not in [k.get("kid") for k in jwks["keys"]]
          else make_resolver(jwks))


def test_tampered_signature_rejected():
    verifier = make_verifier()
    token = mint(base_claims())
    head, payload, sig = token.rsplit(".", 2)[0], token.split(".")[1], token.split(".")[2]
    flipped = ("A" if not sig.startswith("A") else "B") + sig[1:]
    bad = ".".join([token.split(".")[0], payload, flipped])
    with pytest.raises(oidc.InvalidSignature):
        drive(verifier.verify(bad), make_resolver({"keys": [rsa_jwk()]}))


def test_tampered_payload_rejected():
    verifier = make_verifier()
    token = mint(base_claims())
    h, p, s = token.split(".")
    forged = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    forged["email"] = "attacker@example.com"
    bad = ".".join([h, b64u(json.dumps(forged).encode()), s])
    with pytest.raises(oidc.InvalidSignature):
        drive(verifier.verify(bad), make_resolver({"keys": [rsa_jwk()]}))


def test_token_signed_by_wrong_key_rejected():
    verifier = make_verifier()
    token = mint(base_claims(), rsa_key=RSA_KEY_2)  # right kid, wrong key
    with pytest.raises(oidc.InvalidSignature):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


def test_expired_token_rejected():
    verifier = make_verifier()
    token = mint(base_claims(exp=int(time.time()) - 3600))
    with pytest.raises(oidc.InvalidClaims):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


def test_not_yet_valid_nbf_rejected():
    verifier = make_verifier()
    token = mint(base_claims(nbf=int(time.time()) + 3600))
    with pytest.raises(oidc.InvalidClaims):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


def test_future_iat_rejected():
    verifier = make_verifier()
    token = mint(base_claims(iat=int(time.time()) + 3600))
    with pytest.raises(oidc.InvalidClaims):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


def test_missing_exp_rejected():
    verifier = make_verifier()
    claims = base_claims()
    del claims["exp"]
    with pytest.raises(oidc.InvalidClaims):
        drive(verifier.verify(mint(claims)), make_resolver({"keys": [rsa_jwk()]}))


def test_wrong_audience_rejected():
    verifier = make_verifier()
    token = mint(base_claims(aud="someone-elses.apps.googleusercontent.com"))
    with pytest.raises(oidc.InvalidClaims):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


def test_wrong_issuer_rejected():
    verifier = make_verifier()
    token = mint(base_claims(iss="https://evil.example.com"))
    with pytest.raises(oidc.InvalidClaims):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


def test_alg_none_rejected():
    verifier = make_verifier()
    with pytest.raises(oidc.UnsupportedAlgorithm):
        drive(verifier.verify(mint(base_claims(), alg="none")))


def test_alg_hs256_rejected():
    # Classic alg-confusion attack: HMAC "signed" with the public key.
    verifier = make_verifier()
    with pytest.raises(oidc.UnsupportedAlgorithm):
        drive(verifier.verify(mint(base_claims(), alg="HS256")))


@pytest.mark.parametrize("bogus", [
    "not-a-jwt", "a.b", "a.b.c.d", "", "..",
    "!!!.???.###",  # not base64url
])
def test_malformed_tokens_rejected(bogus):
    verifier = make_verifier()
    with pytest.raises(oidc.MalformedToken):
        drive(verifier.verify(bogus))


def test_non_json_payload_rejected():
    verifier = make_verifier()
    bogus = "%s.%s.%s" % (b64u(b'{"alg":"RS256"}'), b64u(b"not json"), b64u(b"sig"))
    with pytest.raises(oidc.MalformedToken):
        drive(verifier.verify(bogus))


# ---------------------------------------------------------------------------
# kid miss -> refresh-once (key rotation)
# ---------------------------------------------------------------------------

def test_kid_miss_triggers_one_refresh_then_verifies():
    calls = []
    verifier = make_verifier()
    # Warm the cache with the OLD key set.
    drive(verifier.verify(mint(base_claims())),
          make_resolver({"keys": [rsa_jwk()]}, calls))
    assert len(calls) == 1

    # Google rotates: a token under a NEW kid arrives; refresh serves it.
    rotated = {"keys": [rsa_jwk(kid="rotated", key=RSA_KEY_2)]}
    token = mint(base_claims(), kid="rotated", rsa_key=RSA_KEY_2)
    claims = drive(verifier.verify(token), make_resolver(rotated, calls))
    assert claims["sub"]
    assert len(calls) == 2  # exactly one refresh, not one per verify


def test_unknown_kid_after_refresh_raises_key_not_found():
    calls = []
    verifier = make_verifier()
    token = mint(base_claims(), kid="never-existed")
    with pytest.raises(oidc.UnknownSigningKey):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}, calls))
    assert len(calls) == 1  # refreshed once, did not loop


# ---------------------------------------------------------------------------
# JWKS fetch failures
# ---------------------------------------------------------------------------

def test_outcall_failure_becomes_jwks_fetch_error():
    def failing(fut):
        raise OutcallFailed("simulated: no consensus")
    verifier = make_verifier()
    with pytest.raises(oidc.JwksFetchError):
        drive(verifier.verify(mint(base_claims())), failing)


def test_non_200_jwks_becomes_jwks_fetch_error():
    verifier = make_verifier()
    with pytest.raises(oidc.JwksFetchError):
        drive(verifier.verify(mint(base_claims())),
              make_resolver(None, status=503, body=b"upstream sad"))


def test_jwks_without_keys_rejected():
    verifier = make_verifier()
    with pytest.raises(oidc.JwksFetchError):
        drive(verifier.verify(mint(base_claims())),
              make_resolver({"nope": True}))


# ---------------------------------------------------------------------------
# provider pluggability + config guards
# ---------------------------------------------------------------------------

def test_second_provider_via_generic_is_data_not_code():
    provider = oidc.generic(
        issuer="https://token.actions.githubusercontent.com",
        jwks_uri="https://token.actions.githubusercontent.com/.well-known/jwks",
        client_id="https://github.com/sweet-papa-technologies",
        name="github-actions",
    )
    calls = []
    verifier = oidc.OidcVerifier(provider)
    token = mint(base_claims(
        iss="https://token.actions.githubusercontent.com",
        aud="https://github.com/sweet-papa-technologies",
    ))
    claims = drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}, calls))
    assert claims["iss"] == "https://token.actions.githubusercontent.com"
    assert calls == ["https://token.actions.githubusercontent.com/.well-known/jwks"]


def test_generic_provider_does_not_inherit_google_iss_alias():
    # The accounts.google.com short-form exception must not leak to others.
    provider = oidc.generic(
        issuer="https://token.actions.githubusercontent.com",
        jwks_uri="https://token.actions.githubusercontent.com/.well-known/jwks",
        client_id="aud-x",
    )
    verifier = oidc.OidcVerifier(provider)
    token = mint(base_claims(iss="token.actions.githubusercontent.com", aud="aud-x"))
    with pytest.raises(oidc.InvalidClaims):
        drive(verifier.verify(token), make_resolver({"keys": [rsa_jwk()]}))


def test_audience_is_mandatory():
    with pytest.raises(ValueError):
        oidc.google(client_id="")
    with pytest.raises(ValueError):
        oidc.Provider(issuer="https://x", jwks_uri="https://x/jwks", audience=None)


def test_providers_cache_independently():
    """Two providers, same kid: each must verify against ITS OWN keys."""
    google_v = make_verifier()
    other = oidc.OidcVerifier(oidc.generic(
        issuer="https://other.example", jwks_uri="https://other.example/jwks",
        client_id=CLIENT_ID))
    drive(google_v.verify(mint(base_claims())),
          make_resolver({"keys": [rsa_jwk()]}))
    # other.example serves a DIFFERENT key under the same kid; a Google-signed
    # token must not verify there just because the kid matches.
    token = mint(base_claims(iss="https://other.example"))
    with pytest.raises(oidc.InvalidSignature):
        drive(other.verify(token),
              make_resolver({"keys": [rsa_jwk(key=RSA_KEY_2)]}))


# ---------------------------------------------------------------------------
# real Google JWKS shape (captured 2026-07-03 from oauth2/v3/certs)
# ---------------------------------------------------------------------------

GOOGLE_JWKS_SAMPLE = {"keys": [
    {
        "e": "AQAB", "alg": "RS256", "kty": "RSA", "use": "sig",
        "kid": "f36191371c8c4ffd162846cde91a9cb4c2bebae2",
        "n": "pO69ul58xhpxEvsHkAs-4vGIyonZ5bcy-fmsvW2IFHuPyntWLfTbm92pZJ50fx4"
             "DYLthKKiGsdJljcPfUPL4mQqGwsN38MtSCOMPocDrtYlsC2Gk909WYiSlB6g14K"
             "_fIN03CIm50PzIh1ycQL6oGEiwTaIxXD9mnomq0skJK-pTDis4yc5Kr25399Elf"
             "CnNaK3Ln44MHT7qKg7YmLzCkQdgQ3jf-eKvnQr9IkCe27jCGwweO43iRVsz6Tz0"
             "rK5U-zdm7pyIu6oeg2ox8WBv_gkuOo6eq08o3iMwM033Ic3sRa1fwMeaCN0Bqn7"
             "tOJWZ5iYgH-6aAImLsGzZ6fRGGQ",
    },
    {
        "n": "rG1fbBOtB-J4kCRwdZDsC4N5G9bDt6gFBDgC3ta7RlfE5WqF0ckl0iSGsaasasU"
             "0psdKSdQ_Is7G2x0TaAQCjZQv4z66b0JWzcFe5iHRCP5Qaz-m6wXm_bPncZBLkt"
             "KBYu4ge-J_5i6Uxkg8D_RwwMptHLumAUMRfalJlIbQncN-kz27dwAn_vaELRaSe"
             "nIg0JSlpWt7aeNEgmmhGiSi2uK_EeOSOYOv1sllCzN8kv2PECUjVX4TtLrKC7Yb"
             "TLSo_JbfWslbsKdSiMx-VJHMok7pIK_pakEuhTwNuqyg2P7u1ZwH9O2rQVzzN9x"
             "VFUfsS7p1iFUVyvJ13YRFtaJT1w",
        "kid": "bc8f7af58db44cf6eaa2ed10ec80f3408cfde465",
        "use": "sig", "e": "AQAB", "alg": "RS256", "kty": "RSA",
    },
]}


def test_real_google_jwks_parses_and_selects_by_kid():
    """Real key material shapes: 2048-bit n, AQAB e, 40-hex kid."""
    verifier = make_verifier()
    # A well-formed token claiming a REAL Google kid but signed by our key
    # must be REJECTED by Google's real public key — proving the JWKS entry
    # was parsed into a working RSA key (n/e base64url -> bigint) and used.
    token = mint(base_claims(), kid="f36191371c8c4ffd162846cde91a9cb4c2bebae2")
    with pytest.raises(oidc.InvalidSignature):
        drive(verifier.verify(token), make_resolver(GOOGLE_JWKS_SAMPLE))


def test_real_google_jwks_unknown_kid_still_key_not_found():
    verifier = make_verifier()
    token = mint(base_claims(), kid="0000000000000000000000000000000000000000")
    with pytest.raises(oidc.UnknownSigningKey):
        drive(verifier.verify(token), make_resolver(GOOGLE_JWKS_SAMPLE))


# ---------------------------------------------------------------------------
# JWKS outcall determinism — transform_jwks_response
#
# MEASURED (2026-07-03): Google's oauth2/v3/certs serves the SAME key set
# with per-backend JSON field ordering — 12 consecutive fetches returned
# byte-distinct bodies of identical logical content. Each replica fetches
# independently, so without body canonicalization the outcall would
# intermittently fail consensus on a 13-node subnet (while a 1-node local
# replica looks fine). These tests pin the canonicalization contract.
# ---------------------------------------------------------------------------

def http_response(body, headers=(("content-type", "application/json"),
                                 ("date", "Fri, 03 Jul 2026 09:00:00 GMT"))):
    return {
        "status": 200,
        "headers": [{"name": n, "value": v} for n, v in headers],
        "body": body if isinstance(body, bytes) else body.encode("utf-8"),
    }


def test_jwks_transform_makes_field_order_variants_identical():
    # Two serializations of one logical key set, as Google actually serves
    # them: same keys, different field order / whitespace.
    key_a = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": "k1",
             "n": "AQAB" * 8, "e": "AQAB"}
    key_b = {"kid": "k2", "e": "AQAB", "n": "BQAB" * 8,
             "alg": "RS256", "use": "sig", "kty": "RSA"}
    variant_1 = json.dumps({"keys": [key_a, key_b]}, indent=2)
    variant_2 = json.dumps(
        {"keys": [dict(reversed(list(key_b.items()))),
                  dict(reversed(list(key_a.items())))]})
    out_1 = oidc.transform_jwks_response(http_response(variant_1))
    out_2 = oidc.transform_jwks_response(http_response(variant_2))
    assert out_1["body"] == out_2["body"]
    # and the canonical form still parses to the same logical key set
    doc = json.loads(out_1["body"].decode("utf-8"))
    assert [k["kid"] for k in doc["keys"]] == ["k1", "k2"]  # sorted by kid


def test_jwks_transform_strips_volatile_headers():
    out = oidc.transform_jwks_response(http_response('{"keys": []}'))
    names = [h["name"] for h in out["headers"]]
    assert "date" not in names
    assert names == sorted(names)


def test_jwks_transform_passes_non_json_through():
    body = b"<html>502 Bad Gateway</html>"
    out = oidc.transform_jwks_response(http_response(body))
    assert out["body"] == body  # fail loudly via consensus, not silently


def test_verifier_fetch_uses_the_jwks_transform():
    seen = []

    def resolve(fut):
        seen.append(fut.transform_name)
        return jwks_response(fut, {"keys": [rsa_jwk()]})

    drive(make_verifier().verify(mint(base_claims())), resolve)
    assert seen == [oidc.JWKS_TRANSFORM]


def test_transformed_google_body_verifies_end_to_end():
    """Feed the verifier a body exactly as the canister sees it POST-transform
    (canonicalized real-shape JWKS) — the parse/verify path must accept it."""
    jwks_body = json.dumps({"keys": [rsa_jwk(), ec_jwk()]}, indent=2)
    canonical = oidc.transform_jwks_response(http_response(jwks_body))["body"]

    def resolve(fut):
        return fut._wrap_response({
            "status": 200,
            "headers": [{"name": "content-type", "value": "application/json"}],
            "body": canonical,
        })

    claims = drive(make_verifier().verify(mint(base_claims())), resolve)
    assert claims["sub"]


# ---------------------------------------------------------------------------
# decode_jwt (exposed helper)
# ---------------------------------------------------------------------------

def test_decode_jwt_roundtrip_without_verification():
    token = mint(base_claims())
    header, payload, signing_input, signature = oidc.decode_jwt(token)
    assert header["alg"] == "RS256"
    assert payload["aud"] == CLIENT_ID
    assert signing_input.decode("ascii") == token.rsplit(".", 1)[0]
    assert len(signature) == 256  # 2048-bit RSA
