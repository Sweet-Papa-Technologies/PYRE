"""pyre.sign — threshold tECDSA signing (v1.1 Phase 3).

Uses the pure-Python `ecdsa` package (dev/test dependency only) both as
the dev-mode fake key and as the EXTERNAL verifier: the Phase-3 gate is
"a canister signs a payload; the signature verifies externally against
the canister's public key" — these tests prove the verify-externally leg
end-to-end at the unit level; the replica leg runs in e2e.
"""

import base64
import hashlib
import json

import ecdsa as ecdsa_pkg
import pytest

from pyre import sign as psign
from pyre.errors import PyreError
from pyre.outcall import pump_sync
from pyre.sign import SigningFailed


def dev_resolver(fut):
    return fut._resolve_dev()


def b64url_decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def external_verify(pub33, signature64, digest):
    vk = ecdsa_pkg.VerifyingKey.from_string(pub33, curve=ecdsa_pkg.SECP256k1)
    return vk.verify_digest(signature64, digest)


def test_sign_hashes_message_to_digest():
    fut = psign.sign("hello")
    assert fut.digest == hashlib.sha256(b"hello").digest()


def test_sign_digest_requires_32_bytes():
    with pytest.raises(PyreError):
        psign.sign_digest(b"short")


def test_async_handler_signature_verifies_externally():
    async def handler():
        sig = await psign.sign(b"attest me")
        pub = await psign.public_key()
        return sig, pub

    sig, pub = pump_sync(handler(), dev_resolver)
    assert len(sig) == 64 and len(pub) == 33 and pub[0] in (2, 3)
    assert external_verify(pub, sig, hashlib.sha256(b"attest me").digest())


def test_tampered_payload_fails_external_verification():
    async def handler():
        return await psign.sign(b"attest me"), await psign.public_key()

    sig, pub = pump_sync(handler(), dev_resolver)
    with pytest.raises(ecdsa_pkg.BadSignatureError):
        external_verify(pub, sig, hashlib.sha256(b"attest ME").digest())


def test_derivation_paths_give_distinct_keys():
    async def handler():
        a = await psign.public_key(derivation_path=("alice",))
        b = await psign.public_key(derivation_path=("bob",))
        return a, b

    a, b = pump_sync(handler(), dev_resolver)
    assert a != b


def test_jwt_from_async_handler():
    async def handler():
        token = await psign.jwt({"sub": "2vxsx-fae", "iat": 1720000000})
        pub = await psign.public_key()
        return token, pub

    token, pub = pump_sync(handler(), dev_resolver)
    h, p, s = token.split(".")
    assert json.loads(b64url_decode(h)) == {"alg": "ES256K", "typ": "JWT"}
    assert json.loads(b64url_decode(p))["sub"] == "2vxsx-fae"
    digest = hashlib.sha256((h + "." + p).encode()).digest()
    assert external_verify(pub, b64url_decode(s), digest)


def test_jwt_from_generator_handler():
    def handler():
        token = yield from psign.jwt({"n": 1})
        return token

    token = pump_sync(handler(), dev_resolver)
    assert token.count(".") == 2


def test_call_result_err_maps_to_signing_failed():
    fut = psign.sign(b"x")
    with pytest.raises(SigningFailed):
        fut._process_call_result({"Err": "insufficient cycles"})


def test_call_result_ok_extracts_signature():
    fut = psign.sign(b"x")
    assert fut._process_call_result({"Ok": {"signature": b"\x01" * 64}}) == b"\x01" * 64


def test_configure_key_name():
    try:
        psign.configure(key_name="key_1")
        assert psign.sign(b"x").key_name == "key_1"
        assert psign.sign(b"x", key_name="test_key_1").key_name == "test_key_1"
    finally:
        psign.configure(key_name="key_1")


def test_dev_server_resolver_handles_sign_futures():
    from pyre.dev import resolve_outcall_dev

    sig = resolve_outcall_dev(psign.sign(b"via dev server"))
    pub = resolve_outcall_dev(psign.public_key())
    assert external_verify(pub, sig, hashlib.sha256(b"via dev server").digest())


def test_kybra_call_args_shape():
    fut = psign.sign(b"payload", derivation_path=("user", b"\x00\x01"))
    assert fut.derivation_path == [b"user", b"\x00\x01"]
    assert fut.cycles == psign.DEFAULT_SIGN_CYCLES
