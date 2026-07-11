"""Upstash Redis (REST API) over ICP HTTPS outcalls.

    from pyre.adapters import upstash

    redis = upstash.Client(url=UPSTASH_URL, token=UPSTASH_TOKEN)

    @app.get("/hits", update=True)
    async def hits(req):
        n = await redis.get("hits")
        return Response.json({"hits": n})

Every Redis command is POSTed as a JSON array to the REST endpoint —
which is exactly what the platform allows (GET/HEAD/POST only). The
response is `{"result": ...}` or `{"error": "..."}`.

AMPLIFICATION WARNING — the big one for Redis: one canister outcall
executes on every replica, so the command runs ~13x against Upstash.
  - Idempotent commands (GET, SET k v, HSET, SADD, DEL, EXPIRE) are
    safe: 13 executions converge to the same state.
  - NON-idempotent commands (INCR, DECR, APPEND, LPUSH, RPUSH, SPOP)
    are NOT safe: INCR by 1 lands as roughly +13. `command()` refuses
    the known-dangerous ones unless you pass `unsafe_amplified=True`
    (e.g. for a rough hit counter where ~node-count granularity is
    fine). For exact counters, keep the counter in pyre.kv and mirror
    it out with SET — idempotent by construction.

Reads across replicas must also agree byte-for-byte (consensus): a GET
racing an external write can fail consensus — treat as retry-able.
The token rides in canister memory and request headers, visible to node
operators — see docs/secrets-and-outcalls.md.
"""

import json as _json

from pyre.errors import PyreError
from pyre.outcall import DEFAULT_MAX_RESPONSE_BYTES, OutcallFuture
from pyre.compat.urllib_request import default_transform


class UpstashError(PyreError):
    """Upstash returned an error (or the command was rejected locally)."""
    code = "PYRE-UPSTASH"

    status = 502


# Commands whose effect multiplies (or otherwise diverges) under outcall
# fan-out — running them ~13x does NOT converge to a single application.
# An incomplete allowlist is worse than none (callers trust it), so this
# aims to be comprehensive across counters, list/set/zset pops and moves,
# bit ops, streams, HLLs, and TTL-mutating reads.
NON_IDEMPOTENT = frozenset((
    # counters / append
    "INCR", "INCRBY", "INCRBYFLOAT", "DECR", "DECRBY", "APPEND",
    "HINCRBY", "HINCRBYFLOAT", "ZINCRBY", "SETRANGE",
    # push / pop (list, set, zset) — order- or membership-dependent
    "LPUSH", "RPUSH", "LPUSHX", "RPUSHX", "LPOP", "RPOP", "SPOP", "GETDEL",
    "ZPOPMIN", "ZPOPMAX", "LMPOP", "ZMPOP", "LINSERT",
    "BLPOP", "BRPOP", "BZPOPMIN", "BZPOPMAX", "BLMPOP", "BZMPOP",
    # moves between keys
    "SMOVE", "RPOPLPUSH", "LMOVE", "BLMOVE", "BRPOPLPUSH",
    # read-then-write in one shot
    "GETSET", "GETEX",
    # bit ops
    "SETBIT", "BITOP", "BITFIELD",
    # streams / HyperLogLog (each add appends distinct entries per replica)
    "XADD", "PFADD", "PFMERGE",
))


class Client:
    def __init__(self, url, token, *,
                 max_response_bytes=DEFAULT_MAX_RESPONSE_BYTES,
                 cycles=None, transform=default_transform):
        self.base = url.rstrip("/")
        self.token = token
        self.max_response_bytes = max_response_bytes
        self.cycles = cycles
        self.transform = transform

    def command(self, *parts, unsafe_amplified=False):
        """Run one Redis command, e.g. command("SET", "k", "v").

        Awaitable; evaluates to the command's result. Non-idempotent
        commands are refused unless unsafe_amplified=True (see module
        docstring for why).
        """
        if not parts:
            raise UpstashError("empty command")
        name = str(parts[0]).upper()
        if name in NON_IDEMPOTENT and not unsafe_amplified:
            raise UpstashError(
                "%s is not idempotent: outcall fan-out would apply it ~13x. "
                "Keep exact counters in pyre.kv and mirror with SET, or pass "
                "unsafe_amplified=True if approximate effects are acceptable."
                % name
            )
        return _Command(self, [str(p) for p in parts])

    # -- idempotent conveniences --------------------------------------

    def get(self, key):
        return self.command("GET", key)

    def set(self, key, value, *, ex=None):
        parts = ["SET", key, value]
        if ex is not None:
            parts += ["EX", str(int(ex))]
        return self.command(*parts)

    def delete(self, *keys):
        return self.command("DEL", *keys)

    def exists(self, *keys):
        return self.command("EXISTS", *keys)

    def hset(self, key, mapping):
        parts = ["HSET", key]
        for k, v in mapping.items():
            parts += [k, v]
        return self.command(*parts)

    def hgetall(self, key):
        return self.command("HGETALL", key)


class _Command:
    def __init__(self, client, parts):
        self._client = client
        self._parts = parts

    def _future(self):
        return OutcallFuture(
            url=self._client.base,
            method="POST",
            data=_json.dumps(self._parts),
            headers={
                "authorization": "Bearer " + self._client.token,
                "content-type": "application/json",
            },
            transform_name=self._client.transform,
            max_response_bytes=self._client.max_response_bytes,
            cycles=self._client.cycles,
            raise_for_status=False,
        )

    def _gen(self):
        resp = yield self._future()
        try:
            payload = resp.json()
        except Exception:
            raise UpstashError(
                "upstash: unparseable response (HTTP %d)" % resp.status
            )
        if isinstance(payload, dict) and payload.get("error"):
            raise UpstashError("upstash: %s" % payload["error"])
        if resp.status >= 400:
            raise UpstashError("upstash: HTTP %d" % resp.status)
        return payload.get("result") if isinstance(payload, dict) else payload

    def __await__(self):
        return self._gen()

    def __iter__(self):
        return self._gen()
