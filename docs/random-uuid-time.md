# Randomness, UUIDs & timestamps

On ICP, update calls execute **replicated across ~13 nodes**. Anything
nondeterministic — `random.random()`, `uuid.uuid4()`, `datetime.now()`,
`time.time()` — computes a *different* value on every replica, which breaks
consensus (or, in a query, silently gives each caller a different answer).
PYRE wraps the consensus-safe primitives so you never hit that footgun.

> **Import caveat:** the real module files are `pyre/prandom.py`,
> `pyre/ptime.py`, `pyre/puuid.py` (files named `random.py` / `time.py` /
> `uuid.py` would shadow the stdlib inside the Kybra bundle). Use the
> `from pyre import ...` form — the statement form `import pyre.random`
> does **not** work.

```python
from pyre import random as prandom
from pyre import time as ptime
from pyre import uuid as puuid
```

## Timestamps — `pyre.time`

All values derive from `ic.time()` (IC system time in nanoseconds,
identical on every replica). In `pyre dev` they fall back to the host
clock — same API.

```python
@app.get("/now")
def now(req):
    return {
        "s":   ptime.now(),        # epoch seconds (int)
        "ms":  ptime.now_ms(),     # epoch milliseconds (int)
        "ns":  ptime.now_ns(),     # epoch nanoseconds (raw ic.time())
        "iso": ptime.isoformat(),  # "2026-07-01T12:34:56.789012Z"
    }
```

`datetime` itself is fine on ICP *when fed a deterministic timestamp* —
`datetime.utcfromtimestamp(ptime.now())` is consensus-safe. Only the
implicit-clock constructors (`.now()`, `.utcnow()`, `.today()`) are footguns.

## Randomness — `pyre.random`, two honest tiers

| | Tier 1 — DRBG | Tier 2 — `raw_rand` |
|---|---|---|
| Call style | sync | `await` (async) |
| Works in | queries **and** updates | **updates only** |
| Cost | free (pure compute) | one inter-canister round trip / 32 bytes |
| Consensus-safe | yes (deterministic by construction) | yes (subnet threshold-BLS randomness) |
| Predictable by an observer | **yes, in principle** — seeded from public `ic.time()` + a counter | no — cryptographically strong |
| Use for | ids, sampling, shuffling, jitter, `uuid4()` | keys, secrets, auth tokens, lotteries |

### Tier 1 — deterministic per message (queries and updates)

A sha256 counter DRBG seeded from `(ic.time(), a monotonic counter, the
canister id)`. Every replica feeds it identical inputs, so every replica
draws identical values.

```python
@app.get("/roll")
def roll(req):
    return {
        "die":   prandom.randint(1, 6),   # unbiased, inclusive
        "f":     prandom.random(),        # float in [0, 1)
        "pick":  prandom.choice(["a", "b", "c"]),
        "slug":  prandom.token_hex(8),    # 16 hex chars
        "id":    prandom.uuid4(),         # RFC-4122 v4 string
    }
```

`uuid4()` values are unique because `ic.time()` advances each round and the
counter disambiguates draws within a message — but they are **not secret**.

### Tier 2 — cryptographically strong (update calls only)

`raw_bytes(n)` awaits the management canister's `raw_rand` (32 bytes of
threshold-BLS randomness per round trip; larger `n` concatenates calls).

```python
@app.post("/keys")
async def make_key(req):
    secret = await prandom.raw_bytes(32)      # for real secrets
    uid = await prandom.uuid4_strong()        # raw_rand-backed UUID
    ...
```

Calling it from a query route raises `RawRandInQueryContext` — in `pyre dev`
too, so the restriction surfaces before you deploy.

**Optional strengthening:** `await prandom.reseed()` mixes 32 bytes of
`raw_rand` entropy into the tier-1 DRBG (kept in canister memory), making
tier-1 values unreconstructible by outside observers while staying
deterministic across replicas. Run it once from an init/post-upgrade update
if you care.

## Dev-time warnings

`pyre dev` scans your source for the footgun patterns (`import random`,
`import uuid` / `uuid.uuid4(`, `time.time(`, `datetime.now(` /
`datetime.utcnow(`) and prints a pointed warning naming the PYRE
replacement. Commented lines and pyre-blessed spellings never warn.

## Dev fallback

On host CPython (`pyre dev`, unit tests) there are no replicas: the DRBG
seeds from `os.urandom`, `raw_bytes` returns `os.urandom(n)`, and
`pyre.time` reads the host clock. The API is identical either way.
