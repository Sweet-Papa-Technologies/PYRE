"""pyre.sign — threshold signing (tECDSA) via the management canister.

The subnet holds the private key as distributed shares; no single node —
and no canister — ever sees it. The canister asks the management canister
to sign, and the subnet produces a signature cooperatively. There is no
key to steal.

    from pyre import sign

    @app.get("/attest", update=True)
    async def attest(req):
        token = await sign.jwt({"sub": req.caller, "iat": ptime.now()})
        return Response.json({"jwt": token})

Signing is an inter-canister call, so it is async and update-only — the
same rules as HTTPS outcalls. Signatures are secp256k1 ECDSA over a
sha256 digest (JWT alg "ES256K"), 64 raw bytes r||s.

Key names: the dfx 0.32 local replica emulates "key_1" (it also lists
Schnorr and vetKD keys — the CDK just can't reach them yet); mainnet has
"key_1" (production) and "test_key_1" (test-grade). The default "key_1"
therefore works both locally and on mainnet; `sign.configure(...)` to
override.

Kybra 0.7.1 exposes tECDSA only; threshold Schnorr (sign_with_schnorr)
is not in this CDK version and will land when the CDK does.

Dev mode (`pyre dev`, no replica): if the pure-Python `ecdsa` package is
installed in the dev environment, a deterministic per-key fake signing
key stands in so the full flow works locally. It is a DEV KEY — never a
subnet key. Without the package, signing raises with an install hint.
"""

import hashlib
import json as _json

from pyre.errors import PyreError
from pyre.outcall import OutcallFuture, _variant_get

# Mainnet fee for sign_with_ecdsa is ~26.15B cycles on key_1 (less on
# test keys); excess attached cycles are refunded, so default generous.
DEFAULT_SIGN_CYCLES = 30_000_000_000

_config = {
    "key_name": "key_1",
    "cycles": DEFAULT_SIGN_CYCLES,
}


class SigningFailed(PyreError):
    """The management canister rejected or failed the signing call."""

    status = 502


def configure(key_name=None, cycles=None):
    """Set the tECDSA key name ("key_1" | "test_key_1") and/or the
    cycles attached per signing call (excess is refunded)."""
    if key_name is not None:
        _config["key_name"] = str(key_name)
    if cycles is not None:
        _config["cycles"] = int(cycles)


def _key_id(key_name):
    return {"curve": {"secp256k1": None}, "name": key_name or _config["key_name"]}


def _norm_path(derivation_path):
    path = []
    for seg in derivation_path or ():
        if isinstance(seg, str):
            seg = seg.encode("utf-8")
        path.append(bytes(seg))
    return path


class _ManagementFuture(OutcallFuture):
    """A pending management-canister call that is not an HTTPS outcall.

    Subclasses OutcallFuture only to ride the existing pump protocol
    (__await__/__iter__ + the isinstance dispatch in pump/pump_sync);
    it deliberately does not call OutcallFuture.__init__.
    """

    def __init__(self):  # noqa: intentionally not calling super().__init__
        pass

    def _to_kybra_call(self):
        raise NotImplementedError

    def _process_call_result(self, call_result):
        raise NotImplementedError

    def _resolve_dev(self):
        """pyre-dev / unit-test resolution (no replica)."""
        raise NotImplementedError


class SignFuture(_ManagementFuture):
    """A pending sign_with_ecdsa call. Awaits to 64 raw bytes r||s."""

    def __init__(self, digest, derivation_path=(), key_name=None, cycles=None):
        digest = bytes(digest)
        if len(digest) != 32:
            raise PyreError(
                "sign_with_ecdsa signs a 32-byte digest; got %d bytes "
                "(use pyre.sign.sign(message) to hash first)" % len(digest)
            )
        self.digest = digest
        self.derivation_path = _norm_path(derivation_path)
        self.key_name = key_name or _config["key_name"]
        self.cycles = _config["cycles"] if cycles is None else int(cycles)

    def _to_kybra_call(self):
        from kybra.canisters.management import management_canister  # lazy: canister only

        args = {
            "message_hash": self.digest,
            "derivation_path": self.derivation_path,
            "key_id": _key_id(self.key_name),
        }
        return management_canister.sign_with_ecdsa(args).with_cycles(self.cycles)

    def _process_call_result(self, call_result):
        err = _variant_get(call_result, "Err")
        if err is not None:
            raise SigningFailed(
                "sign_with_ecdsa failed (key %r): %s" % (self.key_name, err)
            )
        ok = _variant_get(call_result, "Ok")
        return bytes(ok["signature"] if isinstance(ok, dict) else ok.signature)

    def _resolve_dev(self):
        key = _dev_signing_key(self.key_name, self.derivation_path)
        return key.sign_digest_deterministic(self.digest, hashfunc=hashlib.sha256)


class PublicKeyFuture(_ManagementFuture):
    """A pending ecdsa_public_key call. Awaits to 33 SEC1-compressed bytes."""

    def __init__(self, derivation_path=(), key_name=None):
        self.derivation_path = _norm_path(derivation_path)
        self.key_name = key_name or _config["key_name"]

    def _to_kybra_call(self):
        from kybra.canisters.management import management_canister  # lazy: canister only

        args = {
            "canister_id": None,
            "derivation_path": self.derivation_path,
            "key_id": _key_id(self.key_name),
        }
        return management_canister.ecdsa_public_key(args)

    def _process_call_result(self, call_result):
        err = _variant_get(call_result, "Err")
        if err is not None:
            raise SigningFailed(
                "ecdsa_public_key failed (key %r): %s" % (self.key_name, err)
            )
        ok = _variant_get(call_result, "Ok")
        return bytes(ok["public_key"] if isinstance(ok, dict) else ok.public_key)

    def _resolve_dev(self):
        key = _dev_signing_key(self.key_name, self.derivation_path)
        return key.get_verifying_key().to_string("compressed")


# -- public API --------------------------------------------------------------


def sign(message, derivation_path=(), key_name=None, cycles=None):
    """Sign a message (bytes or str): sha256 then threshold-ECDSA.

    Await it in an update handler; evaluates to 64 raw bytes r||s.
    """
    if isinstance(message, str):
        message = message.encode("utf-8")
    return SignFuture(
        hashlib.sha256(bytes(message)).digest(), derivation_path, key_name, cycles
    )


def sign_digest(digest, derivation_path=(), key_name=None, cycles=None):
    """Sign a precomputed 32-byte sha256 digest."""
    return SignFuture(digest, derivation_path, key_name, cycles)


def public_key(derivation_path=(), key_name=None):
    """This canister's threshold public key (SEC1 compressed, 33 bytes)."""
    return PublicKeyFuture(derivation_path, key_name)


def jwt(claims, headers=None, derivation_path=(), key_name=None, cycles=None):
    """Build a threshold-signed JWT (alg ES256K, secp256k1 + sha256).

    Awaitable in async handlers and yieldable in generator handlers.
    Verify externally against `await sign.public_key()` — see
    scripts/verify_signature.py.
    """
    return _AwaitableOp(_jwt_gen(dict(claims), headers, derivation_path, key_name, cycles))


class _AwaitableOp:
    """Awaitable/yieldable wrapper over a generator that yields futures."""

    def __init__(self, gen):
        self._gen = gen

    def __await__(self):
        return self._gen

    def __iter__(self):
        return self._gen


def _jwt_gen(claims, headers, derivation_path, key_name, cycles):
    header = {"alg": "ES256K", "typ": "JWT"}
    if headers:
        header.update(headers)
    signing_input = b64url(_jwt_json(header)) + "." + b64url(_jwt_json(claims))
    digest = hashlib.sha256(signing_input.encode("ascii")).digest()
    signature = yield SignFuture(digest, derivation_path, key_name, cycles)
    return signing_input + "." + b64url(signature)


def b64url(data):
    """Base64url without padding (RFC 7515 style)."""
    import base64

    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_json(obj):
    return _json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


# -- dev-mode fake keys -------------------------------------------------------

_dev_keys = {}
_dev_warned = False


def _dev_signing_key(key_name, derivation_path):
    try:
        import ecdsa as _ecdsa
    except ImportError:
        raise PyreError(
            "threshold signing needs a replica; for `pyre dev`, install the "
            "pure-Python dev shim: pip install ecdsa"
        )
    global _dev_warned
    if not _dev_warned:
        _dev_warned = True
        print(
            "pyre.sign: DEV MODE — using a deterministic local fake key, "
            "not a subnet threshold key"
        )
    cache_key = (key_name, tuple(derivation_path))
    if cache_key not in _dev_keys:
        seed = hashlib.sha256(
            b"pyre-dev-tecdsa|" + key_name.encode() + b"|" + b"/".join(derivation_path)
        ).digest()
        _dev_keys[cache_key] = _ecdsa.SigningKey.from_string(
            seed, curve=_ecdsa.SECP256k1, hashfunc=hashlib.sha256
        )
    return _dev_keys[cache_key]
