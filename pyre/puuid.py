"""pyre.uuid — consensus-safe UUIDs (aliased as `from pyre import uuid as puuid`).

Thin façade over pyre.prandom so the documented DX works:

    from pyre import uuid as puuid

    puuid.uuid4()                # sync, deterministic-per-message (see pyre.random)
    await puuid.uuid4_strong()   # async, raw_rand-backed (update calls only)

Why not a file named uuid.py? The Kybra bundler flattens modules to
top-level basenames, so uuid.py would shadow the stdlib uuid inside the
canister bundle. Hence pyre/puuid.py and the alias — the statement form
`import pyre.uuid` does NOT work; use `from pyre import uuid as puuid`.
"""

from pyre.prandom import uuid4, uuid4_strong

__all__ = ["uuid4", "uuid4_strong"]
