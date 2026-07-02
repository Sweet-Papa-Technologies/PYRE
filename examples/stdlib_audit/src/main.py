"""PYRE v1.1 Phase-0 stdlib support-matrix audit canister.

Framework-free by design (like phase1_spike): results must reflect the
Kybra 0.7.1 / RustPython platform, not PYRE code.

  audit_import(names)  — comma-separated module names; per-module __import__
                         probe, compact `name=ok` / `name=ERR:...` results.
  probe_footguns()     — exercises the determinism footguns (random, uuid,
                         datetime.now, time.time, os.urandom, secrets,
                         ic.time) and reports the actual values seen.
  probe_hashlib()      — checks hashlib primitives against known vectors
                         for b"abc", plus hmac.
"""

from kybra import ic, query


@query
def audit_import(names: str) -> str:
    results = []
    for name in names.split(","):
        name = name.strip()
        if not name:
            continue
        try:
            __import__(name)
            results.append("%s=ok" % name)
        except BaseException as e:  # noqa: BLE001 — audit wants everything
            msg = str(e).replace("\n", " ")[:120]
            results.append("%s=ERR:%s: %s" % (name, type(e).__name__, msg))
    return ";".join(results)


def _probe(label: str, fn) -> str:
    try:
        return "%s=%s" % (label, fn())
    except BaseException as e:  # noqa: BLE001
        msg = str(e).replace("\n", " ")[:120]
        return "%s=ERR:%s: %s" % (label, type(e).__name__, msg)


@query
def probe_footguns() -> str:
    parts = []

    def _random_twice():
        import random

        return "first=%r second=%r" % (random.random(), random.random())

    parts.append(_probe("random.random_x2", _random_twice))

    def _uuid4():
        import uuid

        return str(uuid.uuid4())

    parts.append(_probe("uuid.uuid4", _uuid4))

    def _dt_now():
        import datetime

        return datetime.datetime.now().isoformat()

    parts.append(_probe("datetime.now", _dt_now))

    def _time_time():
        import time

        return repr(time.time())

    parts.append(_probe("time.time", _time_time))

    def _urandom():
        import os

        return os.urandom(8).hex()

    parts.append(_probe("os.urandom8", _urandom))

    def _secrets():
        import secrets

        return secrets.token_hex(4)

    parts.append(_probe("secrets.token_hex4", _secrets))

    parts.append(_probe("ic.time", lambda: ic.time()))

    return " | ".join(parts)


# Known digests of b"abc" (FIPS / official test vectors).
_ABC_VECTORS = {
    "md5": "900150983cd24fb0d6963f7d28e17f72",
    "sha1": "a9993e364706816aba3e25717850c26c9cd0d89d",
    "sha224": "23097d223405d8228642a477bda255b32aadbce4bda0b3f7e36c9da7",
    "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "sha384": (
        "cb00753f45a35e8bb5a03d699ac65007272c32ab0eded1631a8b605a43ff5bed"
        "8086072ba1e7cc2358baeca134c825a7"
    ),
    "sha512": (
        "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
    ),
    "sha3_256": "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532",
    "blake2b": (
        "ba80a53f981c4d0d6a2797b69f12f6e94c212f14685ac4b74b12bb6fdbffa2d1"
        "7d87c5392aab792dc252d5de4533cc9518d38aa8dbf1925ab92386edd4009923"
    ),
    "blake2s": "508c5e8c327c14e2e1a72ba34eeb452f37458b209ed63a294d999b4c86675982",
    "blake3": None,  # not in CPython hashlib; presence check only
}

_HMAC_K_MSG_SHA256 = "bf1a0c1242929b6464a6c0a9ac6298a67e09bd1cd4ef1f182ce0141691fc17a0"


@query
def probe_hashlib() -> str:
    parts = []
    try:
        import hashlib
    except BaseException as e:  # noqa: BLE001
        return "hashlib=ERR:%s: %s" % (type(e).__name__, str(e)[:120])

    for name in (
        "md5",
        "sha1",
        "sha224",
        "sha256",
        "sha384",
        "sha512",
        "sha3_256",
        "blake2b",
        "blake2s",
        "blake3",
    ):
        expected = _ABC_VECTORS[name]
        try:
            ctor = getattr(hashlib, name, None)
            if ctor is not None:
                got = ctor(b"abc").hexdigest()
            else:
                got = hashlib.new(name, b"abc").hexdigest()
            if expected is None:
                parts.append("%s=present digest=%s" % (name, got))
            elif got == expected:
                parts.append("%s=ok" % name)
            else:
                parts.append("%s=WRONG got=%s" % (name, got))
        except BaseException as e:  # noqa: BLE001
            msg = str(e).replace("\n", " ")[:120]
            parts.append("%s=ERR:%s: %s" % (name, type(e).__name__, msg))

    def _hmac():
        import hmac

        got = hmac.new(b"k", b"msg", "sha256").hexdigest()
        return "ok" if got == _HMAC_K_MSG_SHA256 else "WRONG got=%s" % got

    parts.append(_probe("hmac_sha256", _hmac))

    return " | ".join(parts)
