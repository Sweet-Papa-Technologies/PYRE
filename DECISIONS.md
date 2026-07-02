# DECISIONS.md — pinned platform facts & measurements

Locked decisions from the requirements doc (§11) are not repeated here.
This file holds the Phase-0 pins that the spec required to be confirmed at
build time, plus measured numbers.

## CDK choice (pinned 2026-07-01)

| Fact | Value |
|---|---|
| CDK | **Kybra 0.7.1** (Demergent Labs) — released 2025-05-31, beta, community-maintained under DFINITY grant |
| Interpreter | RustPython (Python 3.10 semantics) compiled to WASM |
| Host Python | 3.10.7 exactly (Kybra requirement; via pyenv) |
| dfx | 0.32.0 (installed via dfxvm; Kybra book nominally pins 0.23.0 — 0.32.0 verified working with the Kybra dfx extension, see below) |
| Alternative considered | **Basilisk** (smart-social-contracts, May 2026): CPython 3.13→WASM, technically superior approach but rejected for the MVP — ~4 GitHub stars, single maintainer, HTTPS outcalls not documented. Outcalls are this project's kill-shot risk; we pin the CDK with documented outcall + transform + stable-structure support. Revisit post-MVP: the pyre runtime layer is deliberately thin (all CDK contact is in each canister's `main.py` + one lazy import in `outcall.py`), so a Basilisk port is contained. |

### Kybra platform surface actually used
- `@query` / `@update`, `Async[T]` generator-based async (`yield` on cross-canister calls)
- `kybra.canisters.management.management_canister.http_request(...).with_cycles(n)` for HTTPS outcalls; transform registered as a `@query` taking `HttpTransformArgs`
- `StableBTreeMap[str, str]` for `pyre.kv` (memory_id=250)
- HTTP gateway interface: user-declared Candid records `http_request` (query) / `http_request_update` (update) with `upgrade: opt bool` — pinned from Kybra's http_counter example, which matches the ICP HTTP-gateway protocol spec

### Async model note (spec §5.2 refinement)
Kybra's async is generator-based, not asyncio. PYRE still delivers the
spec's `async def` + `await` DX: `urlopen()` returns an `OutcallFuture`
whose `__await__` yields itself; `pyre.outcall.pump` drives the handler
coroutine/generator and translates futures ⇄ management-canister calls.
Both `await urllib.urlopen(...)` and `resp = yield urllib.urlopen(...)`
are supported.

## Kybra bundler limitations discovered (inherited-CDK caveats, §4.1)
1. **No import aliases for Candid types** (`from x import Y as Z` breaks type
   resolution) and **no duplicate Candid type names** across modules. PYRE's
   gateway records are therefore named `HttpGatewayRequest`/`HttpGatewayResponse`
   (Candid matches structurally, so the names don't reach the wire).
2. **System-method annotations required:** every Kybra-decorated method —
   including `@init`/`@post_upgrade` hooks — needs an explicit return
   annotation (`-> void`), or kybra_generate fails.
3. **Broken error reporting in Kybra 0.7.1:** when kybra_generate fails,
   the real error is swallowed (`💣 Kybra error: compilation` with nothing
   else; KYBRA_VERBOSE crashes its own error parser). To see the actual
   message, run the generator binary directly:
   `~/.config/kybra/0.7.1/bin/kybra_generate .kybra/<name>/py_file_names.csv main /dev/stdout 0.7.1`
4. **Stale build cache:** `.kybra/<name>/python_source/` is never cleaned
   between builds. After renaming/deleting any bundled module, `rm -rf .kybra`
   or stale copies mix into the next build (symptom: nonsense duplicate-module
   errors, or old code running after "successful" deploys). Also note the
   bundler resolves `pyre` from the repo tree (cwd), not site-packages — repo
   edits are picked up without reinstalling into the venv.
5. **Module-basename flattening:** the bundler copies every bundled module to a
   top-level `<basename>.py` slot in addition to its package dir, and later
   copies win. A user module named like any framework/CDK module basename gets
   silently replaced (this bit us: `pyre/app.py` clobbered the example's
   `app.py`). Mitigation: framework modules renamed to distinctive basenames
   (`application.py`, `http_types.py`); **reserved basenames for user code**:
   `application, http_types, routing, gateway, kv, transform, outcall, errors,
   dev, cli, _runtime, _stubs, urllib_request` plus Kybra's `http, basic,
   bitcoin, tecdsa, principal`. Worth escalating upstream post-MVP.

## HTTPS outcall facts (confirmed from Kybra 0.7.1 API)
- Upstream methods: GET / HEAD / POST only (platform limitation; PYRE raises a typed error for others)
- `max_response_bytes`: caller-set cap, PYRE default 16 384 (platform ceiling 2 MB)
- Cycles: attached per call, excess refunded → PYRE defaults to a generous 3B
- Update-context only; PYRE raises `OutcallInQueryContext` otherwise

## Default transform strip-list (§5.1)
Allowlist, not blocklist: keep `content-type`, `content-encoding`
(lowercased, sorted); strip **all** other headers; body passed through.
Rationale: volatile headers are unenumerable (Date, Set-Cookie, ETag, Age,
Via, CF-Ray, X-Request-Id, X-Served-By, X-Timer, ...); one miss = consensus
failure. Observed strip-list against a real CDN (xkcd via Fastly):
`accept-ranges, age, cache-control, connection, content-length, date, etag,
expires, server, vary, via, x-cache, x-cache-hits, x-served-by, x-timer`.

## §5.4 measurements (local replica, dfx 0.32.0, Kybra 0.7.1, 2026-07-02)

| Measurement | Instructions | Ceiling (query) | Headroom |
|---|---|---|---|
| Trivial query (spike `perf_baseline`) | 40,802 | 5B | ~0.0008% used |
| Routed GET /health (full pyre dispatch) | 608,193 | 5B | ~0.012% used |
| JSON echo w/ path param (`/echo/{name}`) | 675,846 | 5B | ~0.014% used |
| Init / post_upgrade | not measured directly — needs PocketIC instruction reporting (deferred). Upgrades complete in single-digit seconds on the local replica, well inside the install limit. |

**Interpreter lifecycle verified (§5.4 requirement):** Kybra boots RustPython
once at init/post_upgrade and keeps the heap warm — per-request cost of
~0.6M instructions is ~4 orders of magnitude below any plausible interpreter
boot, and `pyre.kv`'s bound backend (created at init) services later
messages. Framework overhead per request is ~0.01% of the query budget;
the headroom is the app developer's.

Re-run with `make budgets` after framework changes; treat >5M instructions
for the /health probe as a regression (≈10× today's cost).

## Mainnet run (Phase-1 final gate + cost addendum) — STAGED, awaiting funding

Prepared 2026-07-02; blocked only on cycles.

- Identity: `pyre-dev` (plaintext, dedicated, low-value). Principal
  `grhy4-bc5a3-5vggk-ebniy-3ghgm-mk4rt-voct4-7dxes-xczyw-gl3er-eae`; ICP
  deposit account `ca2b4eb7d19063df134548929d87a19224ceb8e4c785719b446a60d4aeb46b78`;
  pem backed up to `~/pyre-identity-backup/pyre-dev.pem`. Target 5–10T cycles.
- Spike extended with `fetch_json_normalized(url, fields)` +
  `spike_json_transform`: header allowlist PLUS body-level JSON normalization
  (volatile dotted paths passed via the transform's context blob, canonical
  re-serialization). Verified locally: 3/3 byte-identical against
  https://httpbingo.org/uuid with `uuid` blanked; header-only transform
  correctly leaves the volatile body (the mainnet control case).
- `scripts/mainnet_gate.sh` — control (expect consensus reject, capture text),
  fix (body-normalized, expect 3/3 identical), realistic (worldtimeapi with
  volatile fields blanked). Overridable via CONTROL_URL/REALISTIC_URL envs.
- `scripts/mainnet_cost.sh` — per-query / per-update / per-outcall cycle burn
  via balance deltas, idle-burn line from canister status, and outcall
  amplification counted with a webhook.site token (expect ≈ subnet node count).
- Shim default `max_response_bytes` verified tight (16 384; unit test pins it
  ≤32 768 so nobody silently lands on the ~150x-costlier 2MB platform default).

Run order once funded: `dfx cycles balance --network ic --identity pyre-dev` →
`dfx deploy --network ic --identity pyre-dev` (DFX_WARNING=-mainnet_plaintext_identity)
→ curl https://<rest_api-id>.icp0.io/health (fall back to .raw.icp0.io if the
certified gateway rejects uncertified 2xx — record which) → subnet check via
https://ic-api.internetcomputer.org/api/v3/canisters/<id> (must be a 13/34-node
application subnet) → `bash scripts/mainnet_gate.sh` → `bash scripts/mainnet_cost.sh`
→ record results below.

### Results (run completed 2026-07-02)

**Funding & deployment.** Funded 2.158 ICP total (two transfers) → 3.49T
cycles. Deployed to subnet `e66qm-3cydn-nkf4i-ml...` — a **13-node public
application subnet** (verified via ic-api). Canisters: rest_api
`7me34-syaaa-aaaal-qxeya-cai`, outbound `573y4-2aaaa-aaaal-qxewq-cai`,
phase1_spike `5wyta-miaaa-aaaal-qxexa-cai`.
Cost realities learned: canister creation fee is **500B cycles** (not the
older 100B), and installing the Kybra WASM requires **~370B cycles in the
canister at install time** (interpreter-boot init + memory reserve) — this
is the §5.4 init-cost number in cycle terms. One 690B mistake: deleting an
uninstalled canister does NOT recover its balance (the withdrawal needs a
temp wallet the canister can't afford) — top up before delete, or don't delete.

**Inbound (STEP 2).** `https://7me34-syaaa-aaaal-qxeya-cai.icp0.io/health`
→ HTTP 200 `{"status": "ok"}` from the Python handler, on the **certified**
gateway (uncertified 2xx query responses currently pass icp0.io, matching
local-replica behavior).

**Determinism gate (STEP 3) — FULL PASS.**
- (a) CONTROL (`https://httpbingo.org/uuid`, header-only transform):
  consensus failed exactly as the platform promises. Verbatim:
  `Rejection code 2, No consensus could be reached. Replicas had different
  responses. Details: request_id: 3408331, hashes: [e90ad7fc...: 1], [e2f2d7d6...: 1],
  ...` — **12 distinct hashes, one per responding replica**.
- (b) FIX (`spike_json_transform` blanking `uuid`, canonical re-dump):
  3/3 runs byte-identical (`body_sha256=17b252ac...`, 13 bytes).
- (c) REALISTIC (`https://api64.ipify.org/?format=json` — each replica sees
  its OWN node IP in the body, worst-case body nondeterminism): raw →
  consensus failure; with `ip` normalized → 3/3 byte-identical.
- Endpoint gotcha: outcall targets must be **IPv6-reachable** (replicas
  connect over IPv6; worldtimeapi.org has no AAAA record and fails with
  `Connecting to worldtimeapi.org failed` / timeouts).

**Costs (STEP 4, balance deltas on the 13-node subnet).**
| Item | Measured |
|---|---|
| Idle burn (39.4MB Kybra canister) | 1.87B cycles/day (~0.056T/month ≈ $0.075/mo) |
| Per HTTP query (GET /health) | 3.35M cycles |
| Per HTTP update (POST /items) | 11.6M cycles |
| Per outcall request (GET /quote, 8KB cap, incl. update) | 96.7M cycles |
| Outcall amplification | **1 canister call → 12 upstream requests** (= responding replicas). Upstream rate limits see node-count× traffic. |

**Monthly extrapolation — light food-app-shaped backend** (1 canister,
50k reads + 5k writes + 1k small outcalls/month):
idle 0.056T + queries 0.168T + updates 0.058T + outcalls 0.097T ≈ **0.38T
cycles ≈ $0.50/month** (1T ≈ 1 XDR ≈ $1.32). Even at 10× that traffic ≈ $5/mo.
**Against the $20/month bar: PASS with ~40× headroom.** One-time costs
dominate instead: ~0.87T (~$1.15) per canister to create+install.

**VERDICT: Phase 1 FULLY PASSED on mainnet; platform technically and
economically de-risked for light backends.** Next hardening step per plan:
response certification.

## Response certification design (v1.0, WS-C)

- **Model:** certified routes (`@app.get(path, certified=True)`) are GET query
  routes with static paths. Their responses are re-rendered and committed to
  the hash tree after every update call (state only changes in updates, so
  the snapshot is always current). Queries serve the exact certified bytes.
- **Everything else** is covered by a wildcard skip-certification entry
  (`["http_expr","<*>"]`, `no_certification`) so uncertified routes verify
  structurally at gateways instead of relying on leniency. The trust model:
  certified routes → cryptographically verifiable; other queries → explicit,
  documented opt-out; errors/writes → update calls (consensus-signed).
- Implementation is pure Python (RustPython-safe): ic-hashtree + witnesses,
  CBOR encoder, rep-independent hashing (LEB128 for `:ic-cert-status`),
  minified CEL expressions per the gateway spec EBNF. CDK contact stays
  behind two lazy calls (set_certified_data / data_certificate).
- Certified routes must return 2xx at certification time — anything else is
  a developer error (raises, and update dispatch surfaces it as a loud 500).
- Constraint accepted for v1.0: no path-param certified routes (each concrete
  URL needs its own tree entry; revisit with the collections layer if needed).
- Verifier: `scripts/verify_certification.py` re-implements gateway-side
  verification (decode via cbor2, recompute hashes from wire bytes, root vs
  certified_data, /time freshness). BLS chain left to real gateways.

## v1.0 roadmap build (2026-07-02, local-first per FoFo)

Sequencing call resolved: certification pulled to FIRST (FoFo's call), then
the remaining streams. All local; mainnet push awaits funding.

Delivered: response certification v2 (gateway-verified + independent
verifier; witness caching after the budget gate caught a 23x per-request
regression — 608k → 14M → 5.1M instructions); WS-A CORS/hooks/error
handlers/dict-schema validation; WS-B `pyre.data` collections (schema,
pagination, lazy migration) — the kv stable-map declaration stays templated
in the generated main.py; WS-C `pyre.auth` token middleware + `req.caller` +
dev-time secrets guardrail in kv; WS-D friendly errors (IPv6 hint on outcall
failures, reserved-basename warnings in `pyre new`/`pyre dev`), three
templates (bare-api / crud-kv / outbound-proxy), LICENSE/CONTRIBUTING/PyPI-
ready packaging (v0.2.0, publish needs user creds); WS-E pump edge tests,
budget-regression gate (`make budget-gate`), safe mainnet teardown
(`make teardown-mainnet`, encodes the $0.90 lesson); docs set
(quickstart/concepts/api/troubleshooting) + food_tracker reference app
(auth + data + public certified /summary).

New platform findings this round: RustPython's co_flags bits differ from
CPython (async-handler detection now self-calibrates via
`routing._probe_async_bits`); certified routes execute the hook chain at
certification time (keep them exempt from auth); cbor2 decodes arrays as
tuples (verifier compares structurally).

Still open from the roadmap (v1.0): PocketIC CI harness + init-instruction
measurement; logging/observability surface; static/frontend serving
(v1.0-optional); PyPI publish (user credentials).

## Mainnet verification run — v1.0 final proof (2026-07-02)

Funded 6.34 ICP → 10.28T cycles (8.9T remains on the ledger after the run;
~1.5T consumed, mostly now sitting as canister runway).

**Deploy.** food_tracker created+installed at `7qabn-fyaaa-aaaal-qxe2a-cai`
(0.9T initial + 0.15T top-up); the three existing canisters upgraded (each
upgrade re-pays interpreter init — canisters needed ~0.45T+ balance, hence
0.15T top-ups; "out of cycles: top up with at least N" errors are routine
here, not failures). Lesson: a partial `dfx deploy --network ic` failure
leaves earlier canisters upgraded and later ones stale — verify module
state per canister (we caught rest_api serving old code by the absence of
IC-Certificate headers).

**Certification gate — FULL PASS (the thing only mainnet proves).**
- Production gateway (icp0.io, full verification incl. BLS): certified
  `/health` and `/summary` → HTTP 200.
- Official DFINITY verifier (`@dfinity/response-verification` v3.2.0,
  scripts/bls-verify/) against raw responses: **PASS, v2, BLS signature
  chain validated against the real NNS root key** (IC_ROOT_KEY from
  @dfinity/agent). Note: the package's input Response type uses
  `status_code` (snake_case) — camelCase silently panics the WASM.
- Negative controls — the verifier says NO for the right reasons:
  tampered body → "hash of the request and response was not found in the
  tree at the expression path"; stale (+1h clock) → "Certificate
  verification failed". Never patched a verifier to pass; nothing needed it.
- PYRE's own structural verifier also passes against mainnet responses.

**Determinism gate re-run on mainnet: FULL PASS** (control consensus-reject
captured again; fix + realistic 3/3 byte-identical).

**Food-tracker e2e on mainnet (via the verifying gateway):** 401 without
token; 400 with per-field validation errors; authorized POST → 201 →
automatic re-certification → `/summary` reflects the write AND passes the
official BLS verifier; rest_api data from the previous day's cost run
(`cost-1`) survived all of today's upgrades.

**Costs re-measured WITH certification (13-node subnet):**
| Item | Was (pre-cert) | Now | Note |
|---|---|---|---|
| Per query (certified GET /health) | 3.35M | **97,200 cycles** | 34x cheaper — the old number was inflated by the co_flags bug silently upgrading GETs to updates; true queries are ~0.1M (ingress only), and certified reads serve a cached snapshot |
| Per update (POST /items) | 11.6M | **27.3M** | 2.4x — each write now re-renders + re-certifies snapshots; the price of verifiable reads |
| Per outcall request (8KB) | 96.7M | 100.2M | unchanged in substance |
| Amplification | 12 | **13** | full subnet responded |
| Idle burn | 1.87B/day | 2.10B/day (48.4MB wasm) | framework grew |

**Monthly extrapolation (light backend, 50k reads + 5k writes + 1k
outcalls):** idle 63B + queries 4.9B + updates 136.5B + outcalls 100.2B ≈
**0.31T ≈ $0.40/month** — *cheaper* than the pre-certification estimate;
query-heavy workloads benefit enormously from real query pricing. Still
~50x under the $20/month bar.

**VERDICT: PYRE v1.0's differentiator is proven end-to-end on mainnet.**
Certified reads verify against the network's root of trust via an official
independent implementation, tampering is detected, costs got cheaper, and
the reference app runs the full auth/validate/write/re-certify/verify loop
in production.

## Deferred (tracked, not forgotten)
- **Mainnet runs** (Phase 1 gate final proof + Phase 3 acceptance) — this build targets the local replica only.
- **PocketIC integration tests + budget-regression CI gate** — unit + curl-level e2e exist; PocketIC harness is the follow-up.
- **Init-instruction measurement** — requires PocketIC/instrumented install; per-message numbers are measured via `ic.performance_counter`.
- dfx prints a deprecation notice pointing at `icp-cli`; staying on dfx for the MVP since Kybra's extension targets it.
