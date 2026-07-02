"""PYRE v1.1 Phase-2 crypto proof canister.

Exercises pyre.crypto IN-CANISTER against the _pyre_native Rust extension
(AES-256-GCM / ChaCha20-Poly1305 / blake3). Build with the post-generate
patch pipeline:

    scripts/build_native.sh crypto_demo --install

then:

    dfx canister call crypto_demo aead_roundtrip '("attack at dawn")'
    dfx canister call crypto_demo aead_roundtrip '("attack at dawn")'  # nonce differs
    dfx canister call crypto_demo hash_vectors '()'

The DEMO KEY below is a hardcoded constant so the round-trip is
self-contained. Real canisters must get keys from threshold entropy:
`await prandom.raw_bytes(32)` — see docs/crypto.md (and its threat model:
this protects against external leaks, NOT against node operators).
"""

from kybra import query, update

from pyre import crypto

# Demo only. Never hardcode keys, and never derive them from
# os.urandom/secrets in-canister (constant stubs).
_DEMO_KEY = bytes(range(32))


@update
def aead_roundtrip(plaintext: str) -> str:
    """Encrypt+decrypt with both AEADs; report nonces so two separate
    calls can be compared (they must differ: time/counter advanced)."""
    pt = plaintext.encode("utf-8")
    parts = []

    blob = crypto.aes_gcm_encrypt(_DEMO_KEY, pt, aad=b"demo:aad")
    back = crypto.aes_gcm_decrypt(_DEMO_KEY, blob, aad=b"demo:aad")
    parts.append("aes_gcm.nonce=%s" % blob[: crypto.NONCE_LEN].hex())
    parts.append("aes_gcm.blob_len=%d" % len(blob))
    parts.append("aes_gcm.roundtrip=%s" % ("ok" if back == pt else "FAIL"))

    blob2 = crypto.chacha20poly1305_encrypt(_DEMO_KEY, pt, aad=b"demo:aad")
    back2 = crypto.chacha20poly1305_decrypt(_DEMO_KEY, blob2, aad=b"demo:aad")
    parts.append("chacha.nonce=%s" % blob2[: crypto.NONCE_LEN].hex())
    parts.append("chacha.roundtrip=%s" % ("ok" if back2 == pt else "FAIL"))

    # Tamper detection: flip one ciphertext byte -> AuthenticationFailed.
    tampered = (blob[: crypto.NONCE_LEN]
                + bytes([blob[crypto.NONCE_LEN] ^ 1])
                + blob[crypto.NONCE_LEN + 1:])
    try:
        crypto.aes_gcm_decrypt(_DEMO_KEY, tampered, aad=b"demo:aad")
        parts.append("tamper=NOT-DETECTED-FAIL")
    except crypto.AuthenticationFailed:
        parts.append("tamper=detected")

    # aad mismatch must also fail.
    try:
        crypto.aes_gcm_decrypt(_DEMO_KEY, blob, aad=b"demo:other")
        parts.append("aad_mismatch=NOT-DETECTED-FAIL")
    except crypto.AuthenticationFailed:
        parts.append("aad_mismatch=detected")

    return ";".join(parts)


@query
def hash_vectors() -> str:
    """Known-answer checks for the pyre.crypto hash surface, in-canister."""
    checks = [
        ("sha256", crypto.sha256(b"abc").hex(),
         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
        ("sha3_256", crypto.sha3_256(b"abc").hex(),
         "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532"),
        ("blake2b_32", crypto.blake2b(b"abc").hex(),
         "bddd813c634239723171ef3fee98579b94964e3bb1cb3e427262c8c068d52319"),
        ("blake3", crypto.blake3(b"abc").hex(),
         "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85"),
        ("hmac_sha256", crypto.hmac_sha256(
            b"Jefe", b"what do ya want for nothing?").hex(),
         "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"),
    ]
    parts = []
    for name, got, want in checks:
        parts.append("%s=%s" % (name, "ok" if got == want else "FAIL:" + got))
    ok = crypto.verify_hmac(b"k", b"data", crypto.hmac_sha256(b"k", b"data"))
    bad = crypto.verify_hmac(b"k", b"data", b"\x00" * 32)
    parts.append("verify_hmac=%s" % ("ok" if ok and not bad else "FAIL"))
    return ";".join(parts)
