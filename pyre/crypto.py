"""pyre.crypto — hashing, HMAC, and authenticated encryption for canisters.

=============================================================================
THREAT MODEL — READ THIS BEFORE ENCRYPTING ANYTHING (docs/crypto.md)
=============================================================================
Canister-side encryption with a canister-held key protects against
EXTERNAL exposure: a stolen state backup, a leaked database dump, a
ciphertext-only attacker reading your stable memory. That is real and
worth having.

It does NOT protect against node operators. The key lives in canister
memory, and every node in the subnet holds a full copy of that memory. A
malicious node operator can read your key and decrypt everything. There
is no configuration of this module that changes that.

If you need confidentiality FROM node operators:
  - vetKeys (threshold key derivation, planned for PYRE v1.2) — keys are
    derived by the subnet and never exist in any single place; or
  - bring-your-own-key / client-side encryption, TODAY: the client
    encrypts before sending and decrypts after fetching, and the canister
    only ever stores ciphertext. The canister never holds the key, so
    node operators only ever see ciphertext. pyre.crypto still helps
    here — use aes_gcm_decrypt on the CLIENT, and store the opaque blob
    with pyre.kv on the canister.
=============================================================================

Hashing and HMAC (RustPython-native, audit-verified in-canister):

    from pyre import crypto

    crypto.sha256(b"data")            # 32-byte digest
    crypto.sha512(b"data")
    crypto.sha3_256(b"data")
    crypto.blake2b(b"data")           # digest_size=32 default
    crypto.blake3(b"data")            # needs _pyre_native (or pip blake3 on host)
    mac = crypto.hmac_sha256(key, b"data")
    crypto.verify_hmac(key, b"data", mac)   # constant-time, returns bool

AEAD — AES-256-GCM and ChaCha20-Poly1305:

    blob = crypto.aes_gcm_encrypt(key, b"secret", aad=b"user:42")
    plaintext = crypto.aes_gcm_decrypt(key, blob, aad=b"user:42")

`blob` is nonce(12) || ciphertext || tag(16), one opaque bytes value —
store it, ship it, decrypt it with the same key and aad. Tampering with
any byte (or presenting the wrong aad or key) raises AuthenticationFailed.

KEYS: always 32 bytes, and in a canister they must come from threshold
entropy or off-chain:

    key = await prandom.raw_bytes(32)   # from pyre import random as prandom

NEVER key (or nonce) anything from os.urandom / secrets / random inside a
canister: they are deterministic CONSTANT STUBS under Kybra (verified:
secrets.token_hex(4) returns the same value on every call, forever).
pyre.crypto never touches them in-canister.

NONCES are automatic and consensus-safe: each encrypt call derives a
unique 12-byte nonce from ic.time() and an in-memory counter. All
replicas derive the SAME nonce for the same message — that is required
(replicas must agree byte-for-byte on state), and it is safe because
nonce uniqueness, not unpredictability, is what GCM needs. Uniqueness
holds as long as (ic.time(), counter) never repeats for the same key:
ic.time() is strictly monotonic across canister lifetimes, and the
counter separates multiple encrypts inside one message. Power users can
pass an explicit `nonce=` (12 bytes) — then uniqueness is YOUR problem.

Backends: in-canister the AEAD calls dispatch to `_pyre_native` (Rust,
RustCrypto aes-gcm/chacha20poly1305, wired in by scripts/build_native.sh).
On host CPython (`pyre dev`, unit tests) they use the `cryptography`
package if installed — a dev-only shim, exactly like pyre.sign's ecdsa
shim. Without either, a clear CryptoUnavailable explains what to install.
"""

import hashlib as _hashlib
import hmac as _hmac

from pyre import ptime
from pyre._runtime import in_canister
from pyre.errors import PyreError

KEY_LEN = 32
NONCE_LEN = 12
TAG_LEN = 16


class CryptoUnavailable(PyreError):
    """The requested primitive has no backend in this environment."""
    code = "PYRE-CRYPTO-UNAVAILABLE"


class AuthenticationFailed(PyreError):
    """AEAD open failed: wrong key, tampered ciphertext/nonce, or aad
    mismatch. Deliberately one error for all three — distinguishing them
    would leak information to an attacker."""
    code = "PYRE-CRYPTO-AUTHENTICATION"


def _b(data, what="data"):
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    if isinstance(data, str):
        return data.encode("utf-8")
    raise TypeError("%s must be bytes (or str, encoded as utf-8), got %s"
                    % (what, type(data).__name__))


# ---------------------------------------------------------------------------
# Hashing + HMAC — stdlib hashlib/hmac, native under RustPython
# (v1.1 Phase-0 audit: correct known-answer digests in-canister).
# ---------------------------------------------------------------------------

def sha256(data):
    """SHA-256 digest (32 bytes)."""
    return _hashlib.sha256(_b(data)).digest()


def sha512(data):
    """SHA-512 digest (64 bytes)."""
    return _hashlib.sha512(_b(data)).digest()


def sha3_256(data):
    """SHA3-256 digest (32 bytes)."""
    return _hashlib.sha3_256(_b(data)).digest()


def blake2b(data, digest_size=32):
    """BLAKE2b digest (digest_size bytes, default 32).

    In-canister quirk (found while proving this module): RustPython's
    native hashlib.blake2b is the FIXED 64-byte variant — it rejects the
    digest_size kwarg. digest_size=64 always works everywhere; any other
    size works on host CPython, and in-canister dispatches to the
    _pyre_native extension (which carries a variable-output BLAKE2b at
    ~zero size cost). Without the extension, non-64 sizes raise
    CryptoUnavailable in-canister.
    """
    data = _b(data)
    if not in_canister():
        return _hashlib.blake2b(data, digest_size=digest_size).digest()
    if digest_size == 64:
        return _hashlib.blake2b(data).digest()  # native fixed variant
    try:
        import _pyre_native
    except ImportError:
        raise CryptoUnavailable(
            "blake2b with digest_size != 64 requires the _pyre_native "
            "extension in-canister (RustPython's native blake2b is the "
            "fixed 64-byte variant). Build with scripts/build_native.sh, "
            "or use digest_size=64 / crypto.sha256.")
    return bytes(_pyre_native.blake2b_var(data, digest_size))


def blake3(data):
    """BLAKE3 digest (32 bytes).

    Not in RustPython's hashlib: in-canister this needs the _pyre_native
    extension (scripts/build_native.sh); on host CPython it uses the
    `blake3` pip package if installed.
    """
    data = _b(data)
    try:
        import _pyre_native
        return bytes(_pyre_native.blake3_hash(data))
    except ImportError:
        pass
    if in_canister():
        raise CryptoUnavailable(
            "blake3 requires the _pyre_native extension; build the canister "
            "with scripts/build_native.sh — see docs/crypto.md. (blake2b is "
            "available natively via crypto.blake2b.)")
    try:
        import blake3 as _blake3_host
    except ImportError:
        raise CryptoUnavailable(
            "blake3 on host CPython needs the 'blake3' package: "
            "pip install blake3 (dev-only; in-canister it is provided by "
            "the _pyre_native extension). blake2b needs no extras.")
    return _blake3_host.blake3(data).digest()


def hmac_sha256(key, data):
    """HMAC-SHA256 tag (32 bytes)."""
    return _hmac.new(_b(key, "key"), _b(data), _hashlib.sha256).digest()


def verify_hmac(key, data, mac):
    """Constant-time HMAC-SHA256 verification. Returns True/False.

    Always use this — never `mac == expected` — so timing doesn't leak
    how many leading bytes matched.
    """
    return _hmac.compare_digest(hmac_sha256(key, data), _b(mac, "mac"))


# ---------------------------------------------------------------------------
# AEAD — AES-256-GCM / ChaCha20-Poly1305
# ---------------------------------------------------------------------------

# In-memory nonce counter: separates multiple encrypts within a single
# message (where ic.time() is frozen) and adds margin across messages.
# Resets on upgrade/restart — safe, because ic.time() strictly increases
# across canister lifetimes, so the (time, counter) pair never repeats.
_nonce_counter = 0

_NONCE_TAG = b"pyre-aead-nonce-v1"


def _derive_nonce(t_ns, counter):
    """Deterministic 12-byte nonce from (ic.time() ns, counter).

    Deterministic ON PURPOSE: an update call executes on every replica,
    and all replicas must produce identical ciphertext bytes or the
    subnet cannot reach consensus. Every replica sees the same ic.time()
    and counter, hence the same nonce — correct and required. Two
    *different* messages get different nonces because ic.time() advanced.
    """
    material = (_NONCE_TAG
                + int(t_ns).to_bytes(16, "big")
                + int(counter).to_bytes(8, "big"))
    return _hashlib.sha256(material).digest()[:NONCE_LEN]


def _next_nonce():
    global _nonce_counter
    _nonce_counter += 1
    if in_canister():
        return _derive_nonce(ptime.now_ns(), _nonce_counter)
    # Host CPython (`pyre dev`, tests): os.urandom is REAL entropy here
    # (it is only a stub inside the canister), and random nonces are the
    # standard choice off-chain.
    import os
    return os.urandom(NONCE_LEN)


def _check_key(key):
    key = _b(key, "key")
    if len(key) != KEY_LEN:
        raise ValueError(
            "AEAD key must be exactly %d bytes, got %d. In a canister get "
            "one with `await prandom.raw_bytes(32)` (threshold entropy) — "
            "NEVER from os.urandom/secrets, which are constant stubs "
            "in-canister." % (KEY_LEN, len(key)))
    return key


def _check_nonce(nonce):
    nonce = _b(nonce, "nonce")
    if len(nonce) != NONCE_LEN:
        raise ValueError("explicit nonce must be exactly %d bytes, got %d"
                         % (NONCE_LEN, len(nonce)))
    return nonce


_AEAD_UNAVAILABLE_CANISTER = (
    "AEAD requires the _pyre_native extension, which is not present in "
    "this canister build. Build with scripts/build_native.sh (it patches "
    "the Kybra-generated project to register _pyre_native) — see "
    "docs/crypto.md.")

_AEAD_UNAVAILABLE_HOST = (
    "AEAD on host CPython needs the 'cryptography' package: "
    "pip install cryptography. (Dev-only shim — in-canister the backend "
    "is the _pyre_native Rust extension; see docs/crypto.md.)")


def _native():
    """Return the _pyre_native module, or None on host CPython."""
    try:
        import _pyre_native
        return _pyre_native
    except ImportError:
        if in_canister():
            raise CryptoUnavailable(_AEAD_UNAVAILABLE_CANISTER)
        return None


def _host_aead(alg):
    try:
        from cryptography.hazmat.primitives.ciphers import aead as _aead
    except ImportError:
        raise CryptoUnavailable(_AEAD_UNAVAILABLE_HOST)
    return _aead.AESGCM if alg == "aes" else _aead.ChaCha20Poly1305


def _seal(alg, key, plaintext, aad, nonce):
    key = _check_key(key)
    plaintext = _b(plaintext, "plaintext")
    aad = _b(aad, "aad")
    nonce = _next_nonce() if nonce is None else _check_nonce(nonce)

    native = _native()
    if native is not None:
        if alg == "aes":
            sealed = native.aes256_gcm_seal(key, nonce, plaintext, aad)
        else:
            sealed = native.chacha20poly1305_seal(key, nonce, plaintext, aad)
        return nonce + bytes(sealed)

    cipher = _host_aead(alg)(key)
    return nonce + cipher.encrypt(nonce, plaintext, aad if aad else None)


def _open(alg, key, blob, aad):
    key = _check_key(key)
    blob = _b(blob, "blob")
    aad = _b(aad, "aad")
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise AuthenticationFailed(
            "AEAD blob too short (%d bytes; minimum is nonce %d + tag %d)"
            % (len(blob), NONCE_LEN, TAG_LEN))
    nonce, sealed = blob[:NONCE_LEN], blob[NONCE_LEN:]

    native = _native()
    if native is not None:
        try:
            if alg == "aes":
                return bytes(native.aes256_gcm_open(key, nonce, sealed, aad))
            return bytes(native.chacha20poly1305_open(key, nonce, sealed, aad))
        except ValueError:
            raise AuthenticationFailed(
                "AEAD authentication failed: wrong key, tampered "
                "ciphertext, or aad mismatch.")

    from cryptography.exceptions import InvalidTag
    cipher = _host_aead(alg)(key)
    try:
        return cipher.decrypt(nonce, sealed, aad if aad else None)
    except InvalidTag:
        raise AuthenticationFailed(
            "AEAD authentication failed: wrong key, tampered ciphertext, "
            "or aad mismatch.")


def aes_gcm_encrypt(key, plaintext, aad=b"", nonce=None):
    """Encrypt with AES-256-GCM. Returns nonce||ciphertext||tag as one blob.

    key:   32 bytes — `await prandom.raw_bytes(32)` in-canister, never
           os.urandom/secrets (constant stubs!).
    aad:   optional associated data, authenticated but NOT encrypted;
           the same aad must be presented to decrypt.
    nonce: leave as None (automatic, unique, consensus-safe). Passing an
           explicit 12-byte nonce makes uniqueness per (key, message)
           YOUR responsibility — reuse destroys GCM's security.
    """
    return _seal("aes", key, plaintext, aad, nonce)


def aes_gcm_decrypt(key, blob, aad=b""):
    """Decrypt an aes_gcm_encrypt blob. Raises AuthenticationFailed if the
    key is wrong, the blob was tampered with, or the aad doesn't match."""
    return _open("aes", key, blob, aad)


def chacha20poly1305_encrypt(key, plaintext, aad=b"", nonce=None):
    """Encrypt with ChaCha20-Poly1305 (RFC 8439). Same contract as
    aes_gcm_encrypt: returns nonce||ciphertext||tag, automatic nonce."""
    return _seal("chacha", key, plaintext, aad, nonce)


def chacha20poly1305_decrypt(key, blob, aad=b""):
    """Decrypt a chacha20poly1305_encrypt blob. Raises AuthenticationFailed
    on wrong key, tampering, or aad mismatch."""
    return _open("chacha", key, blob, aad)
