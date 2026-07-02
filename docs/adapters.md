# External database adapters

`pyre.adapters` connects your canister to HTTPS-API databases. The standing
rule: **integration, not hot path.** Your real datastore is `pyre.data` over
stable memory — free, fast, and consensus-native. Adapters are for syncing
with systems that live outside the IC (an existing Supabase project, a
shared cache, an analytics sink).

Both adapters ride PYRE's HTTPS outcalls, so all outcall rules apply:
`update=True` routes only, IPv6-reachable hosts, ~2s consensus latency,
and — the important one — **amplification**.

## The amplification tax (read this once)

One outcall is executed by *every replica on the subnet*: measured **13×**
on the v1.0 subnet. Reads are merely 13× the upstream load. Writes are 13
deliveries of your write — so **every write must be idempotent**:

- delivered 13× `INSERT` with a server-generated id → ~13 rows. Bad.
- delivered 13× *upsert* of a row with a client-generated key → 1 row. Good.

The adapters enforce this shape. Generate keys with `pyre.random`'s
`uuid4()` — consensus-safe, so all 13 replicas send the *same* id.

## Supabase (PostgREST)

```python
from pyre.adapters import supabase
from pyre import random as prandom

db = supabase.Client(url="https://<proj>.supabase.co", anon_key=ANON_KEY)

@app.get("/items", update=True)
async def items(req):
    rows = await db.table("items").select("id,title").eq("done", "false").limit(20)
    return Response.json(rows)

@app.post("/items", update=True)
async def create(req):
    row = {"id": prandom.uuid4(), "title": req.json["title"]}
    await db.table("items").insert(row)        # upsert: idempotent under fan-out
    return Response.json(row, status=201)
```

- `select(cols)` + chainable `eq/neq/gt/gte/lt/lte/like/in_/is_/order/limit/offset/single`.
- `insert(rows)` / `upsert(rows)` — always a PostgREST upsert
  (`resolution=merge-duplicates`); rows must carry their primary key.
- `update(values, key="id")` — update-by-upsert; merges only the given columns.
- `delete()` — **refused**: outcalls support GET/HEAD/POST only, and PostgREST
  deletes need the DELETE verb. Expose a SQL function and call it:

  ```sql
  create function delete_item(item_id uuid) returns void
  language sql security definer as
  $$ delete from items where id = item_id $$;
  ```
  ```python
  await db.rpc("delete_item", {"item_id": item_id})   # POST, idempotent
  ```

Use an **anon key + row-level security**, not your service key: adapter
credentials sit in canister memory and request headers, visible to node
operators — see [secrets-and-outcalls](secrets-and-outcalls.md).

## Upstash Redis (REST)

```python
from pyre.adapters import upstash

redis = upstash.Client(url="https://<db>.upstash.io", token=TOKEN)

await redis.set("greeting", "hello", ex=3600)   # idempotent: safe
value = await redis.get("greeting")
```

Any command via `redis.command("SADD", "tags", "python")`. Non-idempotent
commands (`INCR`, `LPUSH`, `APPEND`, …) are **refused** because fan-out
would apply them ~13×; pass `unsafe_amplified=True` only where approximate
effects are fine (a rough hit counter). For exact counters, keep the count
in `pyre.kv` and mirror it out with `SET`.

## Failure modes you'll actually see

| Symptom | Cause | Fix |
|---|---|---|
| `OutcallFailed ... dns error` | host has no AAAA record | outcall targets must be IPv6-reachable |
| consensus reject on a read | data changed mid-call; replicas saw different bytes | retry; don't poll hot rows |
| `ResponseTooLarge` | row set exceeds `max_response_bytes` (default 16 KB) | `limit()` the query or raise the cap |
| 13 rows from one insert | you bypassed the adapter with a raw POST | use `insert()`/client-generated keys |
