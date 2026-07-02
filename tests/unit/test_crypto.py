"""pyre.crypto — hashing against known vectors, constant-time HMAC verify,
and AEAD (via the dev-only `cryptography` shim, mirroring the in-canister
_pyre_native backend)."""

import pytest

from pyre import crypto
from pyre.crypto import AuthenticationFailed, CryptoUnavailable

try:
    from cryptography.hazmat.primitives.ciphers import aead  # noqa: F401
    HAVE_SHIM = True
except ImportError:  # pragma: no cover - shim is installed in .venv-dev
    HAVE_SHIM = False

aead_only = pytest.mark.skipif(
    not HAVE_SHIM, reason="dev AEAD shim missing: pip install cryptography")

KEY = bytes(range(32))
KEY2 = bytes(range(1, 33))


# ---------------------------------------------------------------------------
# Hashing — known-answer vectors (b"abc", the classic NIST/FIPS test input)
# ---------------------------------------------------------------------------

def test_sha256_known_vector():
    assert crypto.sha256(b"abc").hex() == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_sha512_known_vector():
    assert crypto.sha512(b"abc").hex() == (
        "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f")


def test_sha3_256_known_vector():
    assert crypto.sha3_256(b"abc").hex() == (
        "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532")


def test_blake2b_known_vector():
    # blake2b-256 of b"abc" (digest_size=32)
    assert crypto.blake2b(b"abc").hex() == (
        "bddd813c634239723171ef3fee98579b94964e3bb1cb3e427262c8c068d52319")


def test_blake2b_digest_size():
    assert len(crypto.blake2b(b"abc", digest_size=64)) == 64
    assert crypto.blake2b(b"abc", digest_size=64) != crypto.blake2b(b"abc")


def test_blake2b_in_canister_dispatch(monkeypatch):
    # RustPython's native blake2b is fixed-64-byte only; in-canister the
    # 64-byte path uses hashlib and other sizes need _pyre_native.
    monkeypatch.setattr(crypto, "in_canister", lambda: True)
    host64 = crypto.blake2b(b"abc", digest_size=64)
    monkeypatch.setattr(crypto, "in_canister", lambda: False)
    assert crypto.blake2b(b"abc", digest_size=64) == host64

    monkeypatch.setattr(crypto, "in_canister", lambda: True)
    with pytest.raises(CryptoUnavailable) as e:
        crypto.blake2b(b"abc")  # digest_size=32, no _pyre_native on host
    assert "build_native.sh" in str(e.value)


def test_blake3_known_vector():
    pytest.importorskip("blake3", reason="host blake3 shim not installed")
    assert crypto.blake3(b"abc").hex() == (
        "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85")


def test_str_inputs_are_utf8():
    assert crypto.sha256("abc") == crypto.sha256(b"abc")


def test_non_bytes_rejected():
    with pytest.raises(TypeError):
        crypto.sha256(123)


# ---------------------------------------------------------------------------
# HMAC
# ---------------------------------------------------------------------------

def test_hmac_sha256_known_vector():
    # RFC 4231 test case 2
    assert crypto.hmac_sha256(b"Jefe", b"what do ya want for nothing?").hex() == (
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843")


def test_verify_hmac_roundtrip_and_tamper():
    mac = crypto.hmac_sha256(KEY, b"payload")
    assert crypto.verify_hmac(KEY, b"payload", mac) is True
    assert crypto.verify_hmac(KEY, b"payload2", mac) is False
    assert crypto.verify_hmac(KEY2, b"payload", mac) is False
    tampered = bytes([mac[0] ^ 1]) + mac[1:]
    assert crypto.verify_hmac(KEY, b"payload", tampered) is False


# ---------------------------------------------------------------------------
# AEAD via the dev shim
# ---------------------------------------------------------------------------

@aead_only
@pytest.mark.parametrize("enc,dec", [
    (crypto.aes_gcm_encrypt, crypto.aes_gcm_decrypt),
    (crypto.chacha20poly1305_encrypt, crypto.chacha20poly1305_decrypt),
])
class TestAead:
    def test_roundtrip(self, enc, dec):
        blob = enc(KEY, b"attack at dawn", aad=b"user:42")
        assert dec(KEY, blob, aad=b"user:42") == b"attack at dawn"

    def test_blob_layout(self, enc, dec):
        blob = enc(KEY, b"hi")
        # nonce(12) || ciphertext(len(pt)) || tag(16)
        assert len(blob) == crypto.NONCE_LEN + 2 + crypto.TAG_LEN

    def test_empty_plaintext_roundtrip(self, enc, dec):
        blob = enc(KEY, b"")
        assert dec(KEY, blob) == b""

    def test_tamper_fails(self, enc, dec):
        blob = enc(KEY, b"attack at dawn")
        for i in (0, crypto.NONCE_LEN, len(blob) - 1):  # nonce, ct, tag
            tampered = blob[:i] + bytes([blob[i] ^ 1]) + blob[i + 1:]
            with pytest.raises(AuthenticationFailed):
                dec(KEY, tampered)

    def test_wrong_key_fails(self, enc, dec):
        blob = enc(KEY, b"attack at dawn")
        with pytest.raises(AuthenticationFailed):
            dec(KEY2, blob)

    def test_aad_mismatch_fails(self, enc, dec):
        blob = enc(KEY, b"attack at dawn", aad=b"user:42")
        with pytest.raises(AuthenticationFailed):
            dec(KEY, blob, aad=b"user:43")
        with pytest.raises(AuthenticationFailed):
            dec(KEY, blob)  # missing aad

    def test_nonce_uniqueness_across_calls(self, enc, dec):
        nonces = {enc(KEY, b"same message")[:crypto.NONCE_LEN]
                  for _ in range(64)}
        assert len(nonces) == 64

    def test_explicit_nonce_roundtrip(self, enc, dec):
        nonce = bytes(range(12))
        blob = enc(KEY, b"attack at dawn", aad=b"x", nonce=nonce)
        assert blob[:crypto.NONCE_LEN] == nonce
        assert dec(KEY, blob, aad=b"x") == b"attack at dawn"
        # explicit nonce is deterministic: same inputs -> same blob
        assert enc(KEY, b"attack at dawn", aad=b"x", nonce=nonce) == blob

    def test_explicit_nonce_wrong_length(self, enc, dec):
        with pytest.raises(ValueError):
            enc(KEY, b"x", nonce=b"short")

    def test_bad_key_length(self, enc, dec):
        with pytest.raises(ValueError):
            enc(b"short key", b"x")
        with pytest.raises(ValueError):
            dec(b"short key", b"\x00" * 40)

    def test_truncated_blob(self, enc, dec):
        with pytest.raises(AuthenticationFailed):
            dec(KEY, b"\x00" * (crypto.NONCE_LEN + crypto.TAG_LEN - 1))


@aead_only
def test_aes_and_chacha_blobs_not_interchangeable():
    blob = crypto.aes_gcm_encrypt(KEY, b"attack at dawn")
    with pytest.raises(AuthenticationFailed):
        crypto.chacha20poly1305_decrypt(KEY, blob)


# ---------------------------------------------------------------------------
# Deterministic in-canister nonce derivation
# ---------------------------------------------------------------------------

def test_derive_nonce_deterministic_and_unique():
    t = 1_783_024_113_233_586_001  # a real ic.time() value
    # Same (time, counter) -> same nonce on every replica: required for
    # consensus (all replicas must produce identical ciphertext).
    assert crypto._derive_nonce(t, 1) == crypto._derive_nonce(t, 1)
    assert len(crypto._derive_nonce(t, 1)) == crypto.NONCE_LEN
    # Advancing either time (next message) or counter (same message,
    # next encrypt) changes the nonce.
    assert crypto._derive_nonce(t, 1) != crypto._derive_nonce(t, 2)
    assert crypto._derive_nonce(t, 1) != crypto._derive_nonce(t + 1, 1)


def test_next_nonce_in_canister_path(monkeypatch):
    monkeypatch.setattr(crypto, "in_canister", lambda: True)
    monkeypatch.setattr(crypto.ptime, "now_ns", lambda: 1_700_000_000_000_000_000)
    n1 = crypto._next_nonce()
    n2 = crypto._next_nonce()
    # Time frozen within a message: the counter still separates the nonces.
    assert n1 != n2
    assert len(n1) == len(n2) == crypto.NONCE_LEN


def test_host_nonces_are_random():
    assert crypto._next_nonce() != crypto._next_nonce()


# ---------------------------------------------------------------------------
# Backend dispatch errors
# ---------------------------------------------------------------------------

def test_missing_shim_message(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_cryptography(name, *a, **k):
        if name.startswith("cryptography"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_cryptography)
    with pytest.raises(CryptoUnavailable) as e:
        crypto.aes_gcm_encrypt(KEY, b"x")
    assert "pip install cryptography" in str(e.value)


def test_missing_native_in_canister_message(monkeypatch):
    monkeypatch.setattr(crypto, "in_canister", lambda: True)
    monkeypatch.setattr(crypto.ptime, "now_ns", lambda: 1)
    with pytest.raises(CryptoUnavailable) as e:
        crypto.aes_gcm_encrypt(KEY, b"x")
    assert "build_native.sh" in str(e.value)
