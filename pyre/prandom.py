"""pyre.random — consensus-safe randomness (aliased as `from pyre import random as prandom`).

Why this exists: on ICP, update calls execute replicated across ~13 nodes.
Naive `random.random()` / `uuid.uuid4()` draw host entropy, so every replica
computes a DIFFERENT value — the replicas can't agree and the call breaks
consensus (or, in a query, silently gives each caller a different answer).

PYRE gives you two tiers, honestly labelled:

TIER 1 — sync, deterministic-per-message (queries AND updates):
    from pyre import random as prandom

    prandom.random()      # float in [0, 1)
    prandom.randint(1, 6) # unbiased inclusive range
    prandom.choice(seq)
    prandom.weak_token_hex(16)  # 32 hex chars — non-secret ids ONLY
    prandom.correlation_id()    # readable alias for the same
    prandom.uuid4()             # RFC-4122-shaped v4 UUID string

  These come from a sha256 counter DRBG seeded from (ic.time(), a
  monotonically increasing counter, the canister id). Every replica feeds
  the DRBG identical inputs, so every replica draws identical values —
  consensus-safe *by construction*. The outputs are unpredictable enough
  for ids, sampling, shuffling and jitter, but they are NOT cryptographic:
  ic.time() is public, so an observer who knows the call ordering can
  reproduce the stream. For keys, secrets or auth tokens use tier 2.

TIER 2 — async, cryptographically strong (update calls only):
    raw = await prandom.raw_bytes(32)     # threshold-BLS randomness
    uid = await prandom.uuid4_strong()

  `raw_bytes` awaits the management canister's `raw_rand` — 32 bytes of
  subnet threshold randomness per round trip (concatenated for n > 32).
  It is an inter-canister call, so it works only in update context and
  costs a message round trip.

  `await prandom.reseed()` mixes 32 raw_rand bytes into the tier-1 DRBG
  state (kept in canister memory for the canister's lifetime), upgrading
  tier 1 from "deterministic" to "deterministic AND seeded with entropy
  observers can't reconstruct". Call it once from an init/post-upgrade
  update if you care.

NOTE on imports: the real module file is pyre/prandom.py (a file named
random.py would shadow the stdlib inside the Kybra bundle), so the
statement form `import pyre.random` does NOT work — use
`from pyre import random as prandom` (or `from pyre import prandom`).

Dev fallback: on host CPython (`pyre dev`, unit tests) the DRBG is seeded
from os.urandom and raw_bytes returns os.urandom — the API is identical.
"""

import hashlib

from pyre import ptime
from pyre._runtime import ctx, in_canister
from pyre.errors import PyreError
from pyre.outcall import OutcallFuture, _variant_get

# Domain-separation prefix for DRBG blocks (bump on algorithm changes).
_DRBG_TAG = b"pyre-drbg-v1"

# raw_rand always returns exactly 32 bytes per call.
RAW_RAND_BYTES = 32


class RawRandInQueryContext(PyreError):
    """raw_rand is an inter-canister call: update context only."""
    code = "PYRE-RANDOM-QUERY"


# -- canister id (cheap extra seed material, cached once) ----------------------

_canister_id_cache = None


def _canister_id_bytes():
    global _canister_id_cache
    if _canister_id_cache is None:
        cid = b""
        if in_canister():
            try:
                from kybra import ic

                cid = ic.id().to_str().encode("utf-8")
            except Exception:  # noqa: BLE001 — seed material is best-effort
                cid = b""
        _canister_id_cache = cid
    return _canister_id_cache


# -- tier 1: the deterministic DRBG --------------------------------------------


class _Drbg:
    """sha256 counter DRBG over (entropy, canister id, ic.time(), counter).

    All inputs are identical on every replica executing the same message,
    so all replicas draw identical bytes. The counter is monotonic for the
    canister's lifetime (it lives in canister memory), which keeps outputs
    unique across calls within one message AND across messages that land
    in the same consensus round (same ic.time()). After an upgrade the
    counter resets but ic.time() has advanced, so streams never repeat.
    """

    def __init__(self, time_ns=None, entropy=None):
        # time_ns: injectable for tests; None → pyre.ptime.now_ns, looked up
        # at call time so monkeypatched clocks are honored.
        self._time_ns = time_ns
        if entropy is None:
            # Dev fallback: no replicas to agree with, so seed from the OS.
            # In a canister we start from b"" (see reseed() to strengthen).
            entropy = b"" if in_canister() else _dev_entropy()
        self._entropy = entropy
        self._counter = 0
        self._buffer = b""

    def _now_ns(self):
        fn = self._time_ns
        return fn() if fn is not None else ptime.now_ns()

    def _block(self):
        self._counter += 1
        material = b"".join(
            (
                _DRBG_TAG,
                self._entropy,
                _canister_id_bytes(),
                self._now_ns().to_bytes(16, "big"),
                self._counter.to_bytes(16, "big"),
            )
        )
        return hashlib.sha256(material).digest()

    def take(self, n):
        """n deterministic bytes."""
        while len(self._buffer) < n:
            self._buffer += self._block()
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def mix(self, entropy):
        """Fold new entropy into the state (used by reseed())."""
        self._entropy = hashlib.sha256(_DRBG_TAG + self._entropy + entropy).digest()


def _dev_entropy():
    import os as _os  # lazy: never imported in the canister branch

    return _os.urandom(32)


_drbg = _Drbg()


# -- tier 1 public API ----------------------------------------------------------


def random():
    """Float in [0, 1). Deterministic per message — NOT for secrets."""
    return (int.from_bytes(_drbg.take(7), "big") >> 3) / (1 << 53)


def randint(a, b):
    """Integer in [a, b] inclusive, unbiased (rejection sampling).

    Deterministic per message — NOT for secrets.
    """
    if b < a:
        raise ValueError("randint: empty range [%r, %r]" % (a, b))
    span = b - a + 1
    bits = span.bit_length()
    nbytes = (bits + 7) // 8
    mask = (1 << bits) - 1
    while True:
        value = int.from_bytes(_drbg.take(nbytes), "big") & mask
        if value < span:
            return a + value


def choice(seq):
    """A deterministically random element of a non-empty sequence."""
    if not seq:
        raise IndexError("choice: empty sequence")
    return seq[randint(0, len(seq) - 1)]


def weak_token_hex(n=16):
    """2*n hex chars from the tier-1 DRBG. Fine for correlation ids, slugs,
    and cache-busters — NOT for auth tokens, session ids, API keys, CSRF
    tokens or password-reset codes.

    Deliberately NOT named `token_hex`: the stdlib's `secrets.token_hex` is
    CSPRNG-backed and safe for secrets, but this one is reproducible by
    anyone who knows the (public) call ordering. For anything security-
    bearing use `await raw_bytes(n)` / `await uuid4_strong()` (tier 2).
    """
    return _drbg.take(n).hex()


def correlation_id(n=16):
    """Alias for weak_token_hex() — a readable name for its intended use:
    non-secret request/trace correlation ids. Reproducible; not a secret."""
    return weak_token_hex(n)


def _format_uuid4(raw16):
    """16 raw bytes → RFC-4122 v4 string (version/variant bits set)."""
    b = bytearray(raw16)
    b[6] = (b[6] & 0x0F) | 0x40  # version 4
    b[8] = (b[8] & 0x3F) | 0x80  # variant 10xxxxxx
    h = bytes(b).hex()
    return "-".join((h[0:8], h[8:12], h[12:16], h[16:20], h[20:32]))


def uuid4():
    """RFC-4122-shaped v4 UUID string from the tier-1 DRBG.

    Unique because ic.time() advances per round and the DRBG counter
    disambiguates draws within a message. Unpredictable enough for ids;
    for capability/security tokens use `await uuid4_strong()`.
    """
    return _format_uuid4(_drbg.take(16))


# -- tier 2: raw_rand (async, update-only, cryptographically strong) ------------


class RawRandFuture(OutcallFuture):
    """A pending management-canister raw_rand call.

    Subclasses OutcallFuture so pyre.outcall's pump recognizes and drives
    it through the same generator protocol; the HTTP-specific machinery is
    overridden away. Resolves to exactly 32 bytes.
    """

    def __init__(self):  # noqa: D107 — deliberately NOT calling super().__init__
        if ctx.in_query:
            raise RawRandInQueryContext(
                "raw_rand needs update context; mark the route update=True"
            )

    def _to_kybra_call(self):
        """The real management-canister call (canister runtime only)."""
        from kybra.canisters.management import management_canister  # lazy seam

        return management_canister.raw_rand()

    def _process_call_result(self, call_result):
        """CallResult[blob] → 32 bytes, or a typed error."""
        err = _variant_get(call_result, "Err")
        if err is not None:
            raise PyreError("management canister raw_rand failed: %s" % err)
        return bytes(_variant_get(call_result, "Ok"))

    def __repr__(self):
        return "<RawRandFuture (32 bytes pending)>"


async def raw_bytes(n=RAW_RAND_BYTES):
    """n cryptographically strong bytes from the subnet's threshold-BLS
    randomness tape (management canister raw_rand). Await it in an
    update handler:

        @app.post("/keys")
        async def make_key(req):
            secret = await prandom.raw_bytes(32)
            ...

    Each raw_rand round trip yields 32 bytes; larger n concatenates calls.
    Update context only. Dev fallback: os.urandom(n).
    """
    if n < 0:
        raise ValueError("raw_bytes: n must be >= 0, got %r" % n)
    if ctx.in_query:
        raise RawRandInQueryContext(
            "raw_bytes()/raw_rand needs update context; mark the route update=True"
        )
    if n == 0:
        return b""
    if not in_canister():
        import os as _os

        return _os.urandom(n)
    chunks = []
    got = 0
    while got < n:
        chunk = await RawRandFuture()
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)[:n]


async def uuid4_strong():
    """RFC-4122 v4 UUID drawn from raw_rand (update context only)."""
    return _format_uuid4(await raw_bytes(16))


async def reseed():
    """Mix 32 bytes of raw_rand entropy into the tier-1 DRBG state.

    After this, tier-1 values are still deterministic across replicas but
    no longer reconstructible by an outside observer. State lives in
    canister memory (heap) — re-run from post_upgrade if you rely on it.
    Update context only. Returns None.
    """
    _drbg.mix(await raw_bytes(RAW_RAND_BYTES))
