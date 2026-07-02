# pyre.crypto — hashing, HMAC, and authenticated encryption

## Threat model — read this first

**Canister-side encryption with a canister-held key does NOT protect you
from node operators.** The key lives in canister memory, and every node in
the subnet holds a full copy of that memory. A malicious node operator can
read the key and decrypt everything. No setting in this module changes that.

What it DOES protect against — and this is real value — is **external
exposure**: a stolen or leaked state backup, a published database dump, any
attacker who has your ciphertext but not a subnet node. Encrypt-at-rest with
`pyre.crypto` turns "our whole user table leaked" into "opaque blobs leaked".

If you need confidentiality **from node operators**, you have two options:

1. **vetKeys** (threshold key derivation — planned for PYRE v1.2). Keys are
   derived cooperatively by the subnet and never exist in any single place,
   the same trust model as `pyre.sign`'s threshold ECDSA.
2. **Bring-your-own-key / client-side encryption — available today.** The
   client encrypts before sending and decrypts after fetching; the canister
   only ever stores ciphertext and never holds a key:

   ```python
   # Canister: stores opaque blobs, cannot read them — neither can a node op.
   @app.post("/vault/<name>")
   def store(req, name):
       kv.set("vault:" + name, req.body)   # already encrypted by the client
       return {"ok": True}
   ```

   `pyre.crypto`'s blob format (`nonce || ciphertext || tag`) is standard
   AES-256-GCM / ChaCha20-Poly1305, so clients can produce/consume it with
   any mainstream library (WebCrypto, `cryptography`, libsodium bindings).

Pick the row that matches your adversary:

| You are defending against          | Use                                    |
|------------------------------------|----------------------------------------|
| Leaked backups, ciphertext-only attackers | `pyre.crypto` AEAD, canister-held key |
| Curious/malicious node operators   | client-side encryption now; vetKeys in v1.2 |
| Tampering (integrity, not secrecy) | `hmac_sha256`/`verify_hmac`, or AEAD `aad` |

## Keys: where they must come from

Inside a canister, `os.urandom`, `secrets`, `random`, and `uuid` are
**deterministic constant stubs** (verified in the v1.1 stdlib audit —
`secrets.token_hex(4)` returns the same value on every call, forever).
A key derived from them is a public constant.

```python
from pyre import random as prandom

@app.post("/setup", update=True)
async def setup(req):
    key = await prandom.raw_bytes(32)   # threshold-BLS subnet entropy
    kv.set("aead-key", key)             # remember the threat model above!
    return {"ok": True}
```

Or generate the key off-chain and deliver it to the canister (again: any
key the canister stores is readable by node operators).

## Hashing and HMAC

Backed by RustPython's native `hashlib`/`hmac` (audit-verified digests
in-canister) — no extension needed:

```python
from pyre import crypto

crypto.sha256(b"data")              # 32 bytes
crypto.sha512(b"data")              # 64 bytes
crypto.sha3_256(b"data")            # 32 bytes
crypto.blake2b(b"data")             # 32 bytes (digest_size=32 default)
crypto.blake3(b"data")              # 32 bytes — needs _pyre_native (below)

mac = crypto.hmac_sha256(key, b"data")
crypto.verify_hmac(key, b"data", mac)   # constant-time; use this, not ==
```

Quirks discovered while proving this in-canister:

- RustPython's native `hashlib.blake2b` is the **fixed 64-byte** variant —
  it rejects the `digest_size` kwarg. `crypto.blake2b` hides this:
  `digest_size=64` is native everywhere; other sizes use `_pyre_native`'s
  variable-output BLAKE2b in-canister (and plain hashlib on the host).
- `blake3` is not in RustPython's hashlib at all; it comes from the
  `_pyre_native` extension (measured cost: ~15 KB raw wasm). On host
  CPython, `pip install blake3` provides the dev shim.

## AEAD — authenticated encryption

AES-256-GCM and ChaCha20-Poly1305 (RFC 8439):

```python
blob = crypto.aes_gcm_encrypt(key, b"secret", aad=b"user:42")
plaintext = crypto.aes_gcm_decrypt(key, blob, aad=b"user:42")

blob = crypto.chacha20poly1305_encrypt(key, b"secret")
plaintext = crypto.chacha20poly1305_decrypt(key, blob)
```

- `blob` is `nonce(12) || ciphertext || tag(16)` — one opaque bytes value.
- `aad` (optional) is authenticated but not encrypted; decrypt must present
  the same bytes. Use it to bind ciphertext to its context (record id,
  caller principal) so blobs can't be swapped between records.
- Wrong key, any tampered byte, or an aad mismatch raises
  `crypto.AuthenticationFailed` — one error for all three, deliberately.
- Keys are exactly 32 bytes for both algorithms.

### Nonces are automatic — and deterministic on purpose

Every replica in the subnet executes your update call and **must produce
byte-identical state**, so a random nonce is not just unavailable
(no entropy source), it would be *wrong*. `pyre.crypto` derives each nonce
as `sha256("pyre-aead-nonce-v1" || ic.time() || counter)[:12]`:

- all replicas derive the **same** nonce for the same message — required
  for consensus, and safe: GCM needs nonce *uniqueness*, not secrecy;
- two **different** update calls get different nonces (`ic.time()` is
  strictly monotonic, and it never repeats across upgrades/restarts, so
  the in-memory counter resetting is harmless);
- multiple encrypts inside one message are separated by the counter.

Uniqueness therefore holds per key for a canister's lifetime. The residual
caveat: it is a 96-bit hash-derived nonce, so the generic birthday bound
(~2^48 messages per key) applies — rotate keys long before that.

Power users can pass `nonce=` (exactly 12 bytes) to the encrypt functions;
then uniqueness per `(key, message)` is your responsibility — reusing a
nonce with the same key destroys GCM/Poly1305 security completely.

On host CPython (`pyre dev`, tests) nonces come from `os.urandom`, which is
real entropy off-chain.

## Backends and the build pipeline

| Environment | Hashing/HMAC | AEAD + blake3 |
|---|---|---|
| In-canister | RustPython native hashlib/hmac | `_pyre_native` Rust extension |
| Host CPython (dev/tests) | stdlib | `cryptography` package (dev-only shim) |

`_pyre_native` wraps the audited RustCrypto crates (`aes-gcm` 0.10.3,
`chacha20poly1305` 0.10.1 — NCC Group audit, 2020) plus `blake3` 1.5.5 and
`blake2` 0.10.6, sources in `pyre_native/`. Kybra regenerates its Rust
project on every build, so the extension is wired in by a scripted
post-generate patch:

```sh
scripts/build_native.sh <canister_name> --install
```

which runs the normal `dfx build`, copies `pyre_native/src/pyre_native.rs`
into the generated crate, injects the pinned dependencies, registers the
module on the VM (init + post_upgrade), re-runs cargo (seconds — warm
target dir), and re-runs `wasi2ic`. The final wasm lands exactly where dfx
expects it. Measured size cost of the whole extension: **+69 KB raw /
+26 KB gzipped** on a ~27 MB canister — far inside the size gate.

Without the extension, hashing/HMAC still work everywhere; the AEAD
functions raise `CryptoUnavailable` with the build instruction. On the
host, `pip install cryptography` enables the dev shim (mirrors how
`pyre.sign` uses the `ecdsa` package in dev).

A working proof canister lives at `examples/crypto_demo` (round-trip,
tamper/aad-mismatch detection, hash known-answer vectors, and
different-nonces-across-calls, all runnable via `dfx canister call`).
