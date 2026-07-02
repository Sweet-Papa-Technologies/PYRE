"""pyre.time — consensus-safe timestamps (aliased as `from pyre import time as ptime`).

On ICP, update calls execute replicated across ~13 nodes. Host wall-clock
sources (`time.time()`, `datetime.now()`, `datetime.utcnow()`) return a
different value on every replica, which breaks consensus — or, in a query,
silently gives each caller a different answer.

Kybra exposes `ic.time()`: the IC system time in **nanoseconds**, identical
on every replica within a message. Everything in this module derives from
that single source.

    from pyre import time as ptime

    ptime.now()        # epoch seconds (int)
    ptime.now_ms()     # epoch milliseconds (int)
    ptime.now_ns()     # epoch nanoseconds (int) — raw ic.time()
    ptime.isoformat()  # "2026-07-01T12:34:56.789012Z" (UTC, ISO-8601)

NOTE on imports: the real module file is pyre/ptime.py (a file named
time.py would shadow the stdlib `time` inside the Kybra bundle), so the
statement form `import pyre.time` does NOT work — use
`from pyre import time as ptime` (or `from pyre import ptime`).

`datetime` itself is fine on ICP *when fed a deterministic timestamp*:
`datetime.utcfromtimestamp(ptime.now())` is consensus-safe. Only the
implicit-clock constructors (.now()/.utcnow()/today()) are footguns.

Dev fallback: on host CPython (`pyre dev`, unit tests) there is no replica,
so these functions read the host clock — the API is identical.
"""

from pyre._runtime import in_canister

NS_PER_S = 1_000_000_000
NS_PER_MS = 1_000_000


def now_ns() -> int:
    """Epoch nanoseconds. In a canister this is `ic.time()` — identical on
    every replica for the current message. On the host: the host clock."""
    if in_canister():
        from kybra import ic  # lazy: host CPython never takes this branch

        return int(ic.time())
    return _dev_now_ns()


def _dev_now_ns() -> int:
    """Host-clock fallback for `pyre dev` and unit tests."""
    import time as _time

    return _time.time_ns()


def now() -> int:
    """Epoch seconds (int), from the same consensus-safe source."""
    return now_ns() // NS_PER_S


def now_ms() -> int:
    """Epoch milliseconds (int), from the same consensus-safe source."""
    return now_ns() // NS_PER_MS


def isoformat() -> str:
    """Current UTC time as ISO-8601, e.g. '2026-07-01T12:34:56.789012Z'.

    Built from the consensus-safe epoch value with
    datetime.utcfromtimestamp — deterministic because its *input* is.
    Microsecond precision (ic.time()'s sub-microsecond digits are dropped).
    """
    from datetime import datetime as _datetime  # lazy: keep canister import cheap

    ns = now_ns()
    stamp = _datetime.utcfromtimestamp(ns // NS_PER_S).replace(
        microsecond=(ns % NS_PER_S) // 1_000
    )
    return stamp.isoformat() + "Z"
