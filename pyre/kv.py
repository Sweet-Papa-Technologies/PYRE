"""pyre.kv — a tiny key-value store over ICP stable memory (§5.7).

Values are JSON-encoded, so anything json.dumps can handle is storable.
Data lives in a StableBTreeMap and therefore survives canister upgrades.

Query/update honesty: writes from a query-context handler raise
KvWriteInQueryContext instead of being silently discarded by the replica.

In dev mode (host CPython) the backend is an in-memory dict — state lives
for one `pyre dev` process, which is fine for iteration.
"""

import json as _json

from pyre._runtime import ctx, in_canister
from pyre.errors import KvWriteInQueryContext

# StableBTreeMap sizing. Keys/values are length-checked here so devs get
# a PyreError instead of a stable-structures trap.
MAX_KEY_SIZE = 1_024
MAX_VALUE_SIZE = 64_000
_MEMORY_ID = 250  # high id to stay clear of user-defined stable structures


class _DevBackend:
    def __init__(self):
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def insert(self, key, value):
        self._store[key] = value

    def remove(self, key):
        return self._store.pop(key, None)

    def keys(self):
        return list(self._store.keys())


# Kybra discovers StableBTreeMaps by static analysis of the canister's own
# modules, so the map cannot be created here. The canister's main.py declares
#   pyre_kv_store = StableBTreeMap[str, str](memory_id=250, ...)
# and calls bind_backend(pyre_kv_store); dev/tests use the in-memory default.
_backend = _DevBackend()


def bind_backend(backend):
    """Attach the stable-memory backend (called from the canister main.py)."""
    global _backend
    _backend = backend


def _check_writable(operation):
    if ctx.in_query:
        raise KvWriteInQueryContext(
            "kv.%s() needs update context: mark the route update=True "
            "(POST/PUT/DELETE routes are updates by default)" % operation
        )


def _check_key(key):
    if not isinstance(key, str):
        raise TypeError("kv keys must be str, got %s" % type(key).__name__)
    if len(key.encode("utf-8")) > MAX_KEY_SIZE:
        raise ValueError("kv key exceeds %d bytes" % MAX_KEY_SIZE)


# Dev-time confidentiality guardrail (§WS-C): canister state is visible to
# node providers — warn (once per name, host-side only) when an obvious
# secret is written in plaintext. Store hashes instead; see pyre.auth docs.
_SECRET_MARKERS = ("password", "passwd", "secret", "token", "api_key", "apikey", "private_key")
_warned_secret_names = set()


def _warn_if_secret(key, value):
    if in_canister():
        return  # zero overhead on-chain; the guardrail is a dev-time aid
    names = [key]
    if isinstance(value, dict):
        names.extend(str(k) for k in value.keys())
    for name in names:
        lowered = name.lower()
        if lowered in _warned_secret_names:
            continue
        if any(marker in lowered for marker in _SECRET_MARKERS):
            _warned_secret_names.add(lowered)
            import sys

            sys.stderr.write(
                "pyre kv: WARNING — %r looks like a secret. Canister state is "
                "readable by node providers; store a hash instead (see pyre.auth docs)\n"
                % name
            )


def set(key, value):
    """Store a JSON-serializable value under key."""
    _check_writable("set")
    _check_key(key)
    _warn_if_secret(key, value)
    encoded = _json.dumps(value)
    if len(encoded.encode("utf-8")) > MAX_VALUE_SIZE:
        raise ValueError("kv value exceeds %d bytes" % MAX_VALUE_SIZE)
    _backend.insert(key, encoded)


def get(key, default=None):
    """Fetch the value stored under key, or default."""
    _check_key(key)
    encoded = _backend.get(key)
    if encoded is None:
        return default
    return _json.loads(encoded)


def delete(key):
    """Remove key. Returns True if it existed."""
    _check_writable("delete")
    _check_key(key)
    return _backend.remove(key) is not None


def keys():
    """All stored keys (MVP: unordered, no pagination)."""
    return list(_backend.keys())
