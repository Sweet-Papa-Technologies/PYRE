# The mental model — five ICP concepts, honestly explained

PYRE's job is to keep this list short. If you understand these five things,
nothing on-chain should surprise you.

## 1. Query vs. update calls

Every request is one of two kinds:

- **Query** — fast (~100ms), read-only, answered by a single replica.
- **Update** — goes through consensus (~1–2s), can write state and call out.

PYRE maps HTTP onto this automatically: GET routes are queries;
POST/PUT/DELETE routes, `async` handlers, and `update=True` routes are
updates. Browsers never notice — the gateway re-sends upgraded requests —
but writes are visibly slower than reads. That's the platform, not a bug.

Guards: writing `pyre.kv` or awaiting `urlopen` in a query route raises a
typed error, locally and on-chain, instead of being silently discarded.

Wrinkle: PYRE serves **error responses (4xx/5xx) via update calls** so they
arrive consensus-certified (uncertified errors are rejected by verifying
gateways). Fast paths stay queries; failures cost an update round.

## 2. Outbound HTTP is replicated

When your handler calls an API, **every replica in the subnet performs the
call** (~13 of them) and they must agree byte-for-byte on the answer.

Consequences:
- `urlopen` is `await`-able and update-only.
- The upstream server receives ~13 identical requests per canister call —
  mind their rate limits.
- Upstream hosts must be **IPv6-reachable** (`dig AAAA <host>`); replicas
  have no IPv4 path. This kills more integrations than anything else.
- Responses are capped by `max_response_bytes` (default 16KB); bytes cost
  cycles, so the platform's 2MB default is ~150x more expensive.

## 3. The determinism transform

Those ~13 responses differ — `Date` headers, request ids, CDN traces. A
**transform function** canonicalizes each replica's copy before consensus.
PYRE's default keeps only `content-type`/`content-encoding` and passes the
body through. If the **body** is nondeterministic (uuids, timestamps),
register a custom transform in `main.py` that blanks those fields — see
`examples/phase1_spike` for a JSON-normalizing transform driven by the
transform's `context` parameter.

`pyre dev` logs exactly what the transform would strip, per call.

## 4. Certified responses — the reason to be here

On a normal cloud, you trust whoever serves the bytes. On ICP, responses
can carry a **cryptographic certificate** chained to the network's root
key.

- Routes marked `@app.get(path, certified=True)` serve a snapshot whose
  hash is committed to the canister's certified state; the response carries
  `IC-Certificate` headers any client (or the gateway) can verify. Snapshots
  are re-rendered automatically after every update, so they're never stale.
- Constraints: certified routes are GET, static-path, must return 2xx, and
  serve the *certified snapshot* (state changes appear after the write that
  caused them, atomically).
- Everything else is served under an explicit "skip certification" marker —
  structurally valid at verifying gateways, with the trust model on the
  table: certified route = verifiable; other queries = you trust the
  replica that answered; updates/errors = consensus-signed.

Hooks run at certification time, so keep certified routes exempt from auth
middleware (they're for public, verifiable data).

## 5. Canisters are long-lived actors that eat cycles

- The Python interpreter boots once at install/upgrade and stays warm; a
  routed request costs ~0.1% of the per-message instruction budget.
- One-time costs dominate: ~0.5T cycles to create a canister + ~0.4T needed
  in-canister for the runtime install (~$1.15 total). Idle burn for a
  PYRE canister is ~1.9B cycles/day (~$0.075/month).
- Canister state is **readable by node providers**. Never store plaintext
  secrets; store hashes (`pyre.auth` docs show the pattern). PYRE warns at
  dev time if a kv write looks like a secret. Calling external APIs *with*
  a secret key hits the same wall at outcall time — a documented v1.1
  limitation with a workaround: [secrets-and-outcalls.md](secrets-and-outcalls.md).
- If the balance hits zero the canister freezes (and below the freezing
  threshold it can't even be upgraded) — top up before experiments, and use
  `make teardown-mainnet` to reclaim cycles before deleting anything.
