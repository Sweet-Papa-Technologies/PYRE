# DECISIONS.md — pinned platform facts & measurements

Locked decisions from the requirements doc (§11) are not repeated here.
This file holds the Phase-0 pins that the spec required to be confirmed at
build time, plus measured numbers.

## Release 1.3.0 (2026-07-11) — vNext feature release

First release since 1.2.1 (which was security-only). Adds the vNext opt-in
modules and a correctness pass over them. Compiled under Kybra 0.7.1 and
verified end-to-end on a local replica and on mainnet.

**New modules (all opt-in; nothing added to the default canister surface):**
- `pyre.tasks` — durable interval/once timers backed by stable KV, restored
  across install/upgrade; overlap policies (skip/queue_one/allow), catch-up,
  and a bounded async supervisor.
- `pyre.xnet` + `pyre candid` — cross-canister calls over a generated,
  deterministic Candid client (bounded `.did` parser + codegen), with
  principal-checksum validation, request/reply size guards, and cycles/notify.
- `pyre.assets` — generalized chunked asset store in stable memory with
  immutable content-addressed generations, verified atomic publication, HTTP
  ranges, >1.8 MB streaming, three quota levels, and bounded GC.
- `pyre.analytics` — pure-Python, deterministic table/group-by/pivot/join with
  explicit cardinality limits.
- `pyre audit` — dependency/source auditor (AST + `importlib.metadata`) with
  stable JSON and exit codes; flags native/non-pure/host-only/RustPython-gap
  packages and secret literals.
- Internals: injectable platform adapter, deterministic lifecycle coordinator,
  versioned stable-key namespaces, and an in-process testing client.

**Correctness fixes over the above (each with a regression test):** Candid text
codec now round-trips non-ASCII (`\u{...}`/byte escapes, not JSON `\uXXXX`);
candid parser resolves aliases in linear time and caps nesting; task schedule
changes reconcile on upgrade; asset ranges index by the manifest's chunk size,
clamp an over-long end (RFC 7233), and republished generations survive GC;
identical content re-uploads after delete; audit no longer mangles package
names; analytics pivot rejects an index/column name collision. Full suite:
**426 passing**.

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

---

# v1.1 build — "Safe & Capable" (2026-07-02)

Spec: ROADMAP.MD (v1.1 section). Theme: eliminate ICP's determinism
footguns and expose its differentiated capabilities (threshold signing,
strong randomness, external data) behind ordinary-looking Python, without
growing the concept budget. Built with parallel agents; every module
landed with unit tests; Phase-0 safety net (audit + CI + size gate) first,
per ratified decision #2/#4.

## Repo hygiene (same day)
GitHub remote is live (github.com/Sweet-Papa-Technologies/PYRE). The
initial push had accidentally included scripts/bls-verify/node_modules
(926 files) and a garbage commit message (a litellm error string). Fixed
by rewriting the single-commit history: node_modules/ added to .gitignore,
`git rm -r --cached`, amend + force-push. Rule: never trust an
auto-generated commit message you didn't read.

## Phase 0a — stdlib support-matrix audit (docs/stdlib-matrix.md)
Probed all 217 public `sys.stdlib_module_names` in-canister
(examples/stdlib_audit, kept in repo + dfx.json): **142 ok / 75 clean
import-errors / 0 traps.** Root causes: no _socket (socket, ssl,
http.client, urllib.request, smtplib, email.message), no _signal
(subprocess, unittest, platform), no select (asyncio), missing C
extensions (sqlite3, ctypes, bz2, lzma, zoneinfo, mmap).

**The audit's two headline findings:**
1. **In-canister entropy sources are CONSTANT STUBS, not merely
   nondeterministic.** `random.random()` restarts the identical stream
   every message; `uuid.uuid4()` returns the *same UUID forever*
   (10b0a742-f1e4-4238-a7a4-5cae054ec21c); `os.urandom(8)`/`secrets.*`
   return fixed bytes — in updates as well as queries. Only
   `management_canister.raw_rand()` is real entropy. This upgraded
   pyre.random from "nice DX" to "safety-critical".
2. **pathlib is broken** (os.chmod unimplemented; also kills zipfile,
   importlib.metadata/resources). Canister code uses os.path. Corollary
   gotcha: top-level import success ≠ working package (email, http).

Nice doc story confirmed: `datetime.now()`/`time.time()` ARE `ic.time()`
(consensus time) to the nanosecond — timestamps are safe; entropy is not.
hashlib is real and correct (known-answer verified): md5/sha1/sha2
family/sha3_256/blake2b/blake2s + hmac. blake3 absent. No AEAD anywhere.

## Phase 0b — CI foundation
- **PocketIC harness** (tests/pocketic/, pocket-ic==3.1.2 + server 13.0.0
  pinned; scripts/pocketic_setup.sh): 8 canister-level tests against the
  prebuilt wasm — health query, 404-upgrade path, path params,
  IC-Certificate presence, write persistence, upgrade survival, and the
  two budget assertions. **Init measured: 63.24B cycles**
  (install_chunked_code, deterministic; ≈150B instructions of RustPython
  boot — threshold 80B). Per-request instructions via pyre_perf_probe:
  /health 3.37M, /echo 4.17M, /items 5-6M (threshold 7.5M).
  Kybra-specific handling that cost real effort: PocketIC enforces the
  2MiB ingress limit → chunked install required; ic-py Vec(Nat8) is
  byte-at-a-time slow → bulk-blob fast path; back-to-back installs hit
  CanisterInstallCodeRateLimited → advance_time(60s) retry.
- **Size/idle gate** (scripts/size_gate.sh + size_thresholds.env, wired
  into `make budget-gate`): raw + gz wasm per canister vs recorded
  baselines (~27.3MB raw / ~14.2MB gz; thresholds +10%). Idle-burn proxy
  documented: ~44M cycles/MB/day (mainnet-measured). "Adding a fat crate
  fails CI" is now enforceable.
- **GitHub Actions** (.github/workflows/ci.yml): unit-tests job (fast,
  dependency-free), wasm-build job (dfxvm + kybra, cached ~/.config/kybra
  + ~/.cargo, uploads wasm artifact, runs size gate), pocketic job
  (artifact-fed). publish.yml: release → build → PyPI via trusted
  publishing. NOTE: wasm-build/pocketic jobs validated locally in shape
  only — first real push proves them.

## Phase 1 — consensus-safe randomness/UUIDs/time (pyre/prandom.py, ptime.py, puuid.py)
Two honest tiers:
- Sync (queries+updates): sha256-counter DRBG seeded per-message from
  `sha256(tag‖entropy‖canister_id‖ic.time()‖counter)` — identical on
  every replica by construction → consensus-safe; unique across messages
  because time advances and the counter persists on the heap. random(),
  randint() (rejection-sampled, unbiased), choice(), token_hex(), uuid4()
  (correct v4 version/variant bits).
- Async (updates only): `await raw_bytes(n)` over management raw_rand
  (threshold BLS), `await uuid4_strong()`, `await reseed()` mixes real
  entropy into the DRBG. Rides the existing outcall pump via a
  RawRandFuture(OutcallFuture) subclass — zero pump changes.
DX spelling: `from pyre import random as prandom` etc. — implementation
files are prandom/ptime/puuid because a pyre file named random.py/uuid.py/
time.py would shadow the stdlib inside Kybra's flattened bundle (the v1.0
basename lesson, now load-bearing API design). `import pyre.random` as a
statement deliberately doesn't exist.
`pyre dev` now scans user code and warns on: import random / uuid.uuid4 /
datetime.now / time.time / **os.urandom / import secrets** (the last two
added after the audit's constant-stub finding).

## Phase 3 — threshold signing (pyre/sign.py) — tECDSA only
**Kybra 0.7.1 has no Schnorr** (tecdsa.py exposes only
sign_with_ecdsa/ecdsa_public_key, curve variant only secp256k1). Decision:
ship tECDSA; document Schnorr as CDK-gated rather than hand-rolling a
custom aaaaa-aa Service for it (mechanism exists — call_raw/candid_encode
— but hand-built candid for a security API is exactly the kind of
cleverness v1.1 fences off). Revisit at the next CDK bump.
Surface: `await sign.sign(msg)` (sha256→64-byte r‖s), sign_digest,
`await sign.public_key()` (SEC1 compressed), `await sign.jwt(claims)` —
ES256K JWT, awaitable AND yieldable (generator-composable _AwaitableOp).
Key names: dfx_test_key default, configure(key_name="key_1") for mainnet;
30B cycles attached (fee ~26.15B, excess refunded). Futures subclass
OutcallFuture to ride the pump — same seam as raw_rand; pyre/dev.py
resolves any future exposing `_resolve_dev()` (sign uses a deterministic
LOCAL fake key via the pure-python `ecdsa` package, dev-only, loud
banner). External verification: scripts/verify_signature.py (jwt + raw
modes, --tamper negative control) — unit-verified against the dev keys;
e2e_local.sh now has attest → external-verify → tamper-reject checks;
gate closes on-replica (dfx_test_key) at the next local run [pending
below]. rest_api example grew /attest + /attest/pubkey.

## Phase 4 — external DB adapters (pyre/adapters/)
Designed around three platform facts: 13× write amplification, GET/HEAD/
POST-only, byte-identical consensus on reads.
- supabase.py (full PostgREST client): chainable select filters;
  **insert() IS an upsert** (resolution=merge-duplicates) and requires
  client-generated primary keys (pyre.random.uuid4 — same id on all 13
  replicas) so fan-out converges to one row; update()=upsert-merge;
  **delete() refuses with a teaching error** (DELETE verb unreachable —
  the blessed path is a SQL function via db.rpc(), POST + idempotent);
  PostgREST errors → typed SupabaseError. Local pure-python percent-encoder
  (urllib.parse works in-canister but keep the dependency surface minimal).
- upstash.py (Redis REST): every command is a POST; **non-idempotent
  commands (INCR/LPUSH/APPEND/…) are refused** unless unsafe_amplified=True,
  with the pattern "keep exact counters in pyre.kv, mirror with SET".
docs/adapters.md leads with the amplification tax; standing rule
"integration, not hot path" stated everywhere. Mainnet leg of the gate
(real Supabase read + idempotent write under fan-out) queued for the
mainnet run.

## Phase 5 — Basic auth + logging
- require_basic() (RFC 7617) alongside require_token: dict of
  {user: sha256_hexdigest} or callable; constant-time compares on bytes
  (hmac.compare_digest verified present in RustPython; pure-python
  fallback shipped anyway); full-dict scan (no user-exists timing leak);
  WWW-Authenticate realm on 401; malformed anything → 401 never 500;
  req.user set on success.
- pyre/log.py: levelled structured logging → ic.print → **retrievable via
  `dfx canister logs`** (the v1.0 observability gap, closed); stderr in
  dev; docs/observability.md (logs are a bounded rolling buffer — not an
  audit trail; controller-visible — never log secrets).
- docs/secrets-and-outcalls.md: the §7 mandated honest limitation — why
  secret-bearing outcalls expose keys to node operators, the self-hosted
  signed-proxy workaround (built on pyre.sign), v1.2 paved path, TEE
  note, never-a-shared-proxy trust model.

## Packaging
PyPI name **pyre-icp** (pyre is taken); import stays `pyre`, CLI stays
`pyre`. Wheel verified in a clean venv: templates ship (15 files),
`pyre new` works from the installed wheel. One-time PyPI setup required:
trusted publisher (project pyre-icp, owner Sweet-Papa-Technologies, repo
PYRE, workflow publish.yml, environment pypi) + matching GitHub
environment. Known cosmetic wart: `pyre new` copies __pycache__ from
installed templates (fix: shutil.ignore_patterns in cli.py).

## Still open at this point in v1.1
- Phase 2 pyre.crypto: Rust-extension investigation in flight (AEAD is
  the genuine gap; hashing ships over native hashlib per audit).
- Rust-extension pattern docs (depends on the above's outcome).
- Local replica regression of the full v1.1 surface + this file's crypto
  section; then the mainnet verification push (user-funded).

## Phase 2 — pyre.crypto + the Rust-extension seam (the v1.1 Kind-B proof)

**VIABLE — shipped.** Kybra 0.7.1's generated Rust project accepts a
native-module patch with NO interpreter-level work. The seam: generated
`.kybra/<c>/src/lib.rs` builds the RustPython VM in exactly two places
(#[init], #[post_upgrade]) via `Interpreter::with_init`, and the pinned
RustPython rev exposes `vm.add_native_module()` publicly. The patch is:
copy one .rs file in, inject 4 pinned dep lines under `[dependencies]`
(NOT at EOF — the generated Cargo.toml ends with `[patch.crates-io]`),
add `mod pyre_native;` + one registration line after each of the two
`add_native_modules(...)` calls. `scripts/build_native.sh` automates it
(normal build → patch → ~5-8s warm cargo re-run → wasi2ic → wasm lands
where dfx expects), asserts exactly 2 registration points, and refuses to
patch if kybra_generate's output shape ever changes.

**Crates (audited RustCrypto only, features trimmed, getrandom OFF —
no ambient entropy in-canister):** aes-gcm =0.10.3, chacha20poly1305
=0.10.1, blake3 =1.5.5, blake2 =0.10.6 (already in the dep graph).
**Measured size deltas:** AEAD +49,315 raw / +17,411 gz; blake3 marginal
+14,950 / +3,887 → INCLUDED (three orders under the 500KB decision bar);
full extension +70,667 / +26,518 = **+0.26%** against ~10% gate headroom.
Size gate: PASS.

**In-canister proof (examples/crypto_demo, local):** FIPS/RFC known-answer
vectors pass; AES-GCM + ChaCha20-Poly1305 round-trip; tamper detected;
AAD mismatch detected; nonces differ across update calls AND within one
call; `_pyre_native` survives upgrades (both registration points live).

**pyre/crypto.py surface:** hash/HMAC over native stdlib hashlib/hmac (per
the ratified "no Rust for what exists" rule); AEAD blob = nonce(12)‖ct‖
tag(16) (WebCrypto-interoperable, enables BYOK); automatic consensus-safe
nonces `sha256("pyre-aead-nonce-v1"‖ic.time()‖counter)[:12]` — identical
across replicas (required), unique per key+message (~2^48 msgs/key
birthday bound documented); explicit nonce= for power users; keys point at
`await prandom.raw_bytes(32)`. Threat model unmissable in module + docs/
crypto.md: canister-held keys are READABLE BY NODE OPERATORS — this
encrypts against external leakage, not against the platform; vetKeys is
the v1.2 answer; BYOK/client-side pattern documented meanwhile. Dev shims
(host only): cryptography + blake3 pip packages.

**Genuine RustPython bug found:** native `hashlib.blake2b` is the fixed
64-byte variant and REJECTS `digest_size` (the Phase-0 audit had only
checked the default). `pyre.crypto.blake2b` dispatches: 64 → native,
other sizes → `_pyre_native.blake2b_var` in-canister.

**Ops notes:** the patched rebuild re-locks Cargo.lock (Kybra regenerates
it anyway); dfx install accepts the raw patched wasm; a backgrounded
`dfx start` dies with its parent shell — start detached (nohup).

## v1.1 local regression — final (2026-07-02, late)

- Unit: 230 passed (was 99 at v1.0). PocketIC: 8/8 (thresholds hold after
  the v1.1 modules: /echo 4.18M, /items 6.02M instructions). Size gate:
  PASS everywhere — the whole v1.1 python surface cost ~+150KB gz per
  canister.
- e2e_local.sh: **20/20** including the new gates: canister-issued
  ES256K JWT verified EXTERNALLY (scripts/verify_signature.py) + tampered
  JWT rejected + pyre.log lines visible via `dfx canister logs`.
- **Phase-3 gate closed on-replica.** Finding along the way: dfx 0.32's
  local replica does NOT ship the old "dfx_test_key" — its enabled key is
  **key_1** (the error listed the full set: ecdsa:Secp256k1:key_1,
  schnorr:Bip340Secp256k1:key_1, schnorr:Ed25519:key_1,
  vetkd:Bls12_381_G2:key_1). So pyre.sign defaults to "key_1", which now
  works locally AND on mainnet unchanged. Bonus intel: the replica already
  has Schnorr + vetKD keys — only the Kybra 0.7.1 binding is missing,
  confirming Schnorr is purely CDK-gated.
- Phase-4 adapters: unit-proven (14 tests) + shape-proven against
  PostgREST/Upstash REST semantics; the mainnet leg of the gate (live read
  + idempotent write under real 13x fan-out) rides the next mainnet run.
- Still pending from v1.1: first real push must validate the wasm-build +
  pocketic GitHub Actions jobs; PyPI trusted-publisher one-time setup;
  mainnet verification run (user-funded) incl. sign-on-mainnet cost check.

## Post-v1.1 watch-items (architect review, 2026-07-03)

- **Init cycles trend (63.2B at v1.1):** interpreter boot is a fixed tax
  on every install/upgrade and grows with the module surface. The PocketIC
  budget gate holds the line at 80B — watch the TREND across releases,
  not just the threshold; this number eventually decides whether a fat
  app can still upgrade itself.
- **The Kybra ceiling tally** (the quiet case for keeping the Basilisk
  seam clean): (1) Schnorr — replica has the keys, CDK lacks the binding;
  (2) the _pyre_native seam patches Kybra's GENERATED crate — a CDK bump
  can break it (build_native.sh asserts loudly if the shape drifts);
  (3) basename flattening constrains framework file naming; (4) the
  Candid no-alias limitation. Each is fine alone; together they say the
  ceiling has Kybra's name on it, not ICP's.
- **Release order (ratified):** tag v1.0.0 in history (done, ca3fb61);
  publish **v1.1.0 as the inaugural PyPI release** AFTER the v1.1 mainnet
  run — verify-then-publish. Version aligned to 1.1.0 (pyproject +
  __version__; they had drifted 0.2.0 vs 0.1.0).
- **The stranger test is still unrun** and got MORE valuable with the
  bigger v1.1 doc surface (crypto threat model, sign, adapters). Run it
  against the PUBLISHED package + docs after the PyPI release; treat
  every stumble as a docs bug.
- **v1.1 mainnet run needs NO new funding:** ledger 8.909T + ~0.4T per
  canister covers upgrades + signing (~26B/sig) + the adapter fan-out
  gate. The adapter gate is the one item local can't fake (real
  PostgREST upsert semantics under real 13x fan-out) — needs a
  user-provided free-tier Supabase project (URL + anon key).

## Fake-entropy DEFUSAL (2026-07-03, post-review hardening)

Review question that triggered it: "did we fix the constant-stub modules,
and why not fix them in place?" Answer recorded:

**Why an in-place fix is impossible-or-dishonest:** the constants come
from the interpreter itself (RustPython/WASI has no entropy source), and
the platform's only real entropy — raw_rand — is an ASYNC system call.
os.urandom/secrets are synchronous APIs with a cryptographic-strength
contract; the only thing we could put behind them synchronously is the
time+counter DRBG, which is consensus-safe but PREDICTABLE — silently
wiring it into `secrets` would turn a visible footgun into an invisible
vulnerability (session tokens derivable from ic.time()). No existing
library can fix this either: nothing can conjure entropy the platform
doesn't expose synchronously. Hence: explicit safe APIs + loud failure.

**What shipped:** install_stubs() (already the socket/threading pattern)
now also DEFUSES the liars in-canister: os.urandom, uuid.uuid4,
secrets.token_bytes/hex/urlsafe/randbits/randbelow/choice, and
secrets/random.SystemRandom all raise FakeEntropyError with pyre.random
guidance. secrets.compare_digest untouched (not entropy); uuid3/uuid5
untouched (hash-based, legitimately deterministic); plain random.random /
datetime / time keep working (non-crypto; dev-warned). Every patch is
individually best-effort (a failed setattr degrades to the old
warned-footgun behavior rather than bricking @init).

**Proven in-canister** (stdlib_audit, now importing pyre precisely to make
probe_footguns the defusal acceptance test): uuid.uuid4/os.urandom/
secrets.token_hex → ERR:FakeEntropyError with guidance; random/datetime/
time/ic.time still report values. setattr on RustPython's Rust-backed
modules sticks. 237 unit tests green (defusal + restore-leak coverage).

Note: mainnet rest_api/food_tracker were upgraded hours BEFORE this
hardening — they run pre-defusal builds (harmless: neither touches the
defused APIs). Picked up at the next natural upgrade; the v1.1.0 tag
includes it.

## Phase-4 finding: Supabase AND Upstash are IPv4-only (2026-07-03)

When the Supabase SaaS outage cleared, the fan-out gate hit a harder
wall: `dig AAAA` is EMPTY for *.supabase.co (project hosts and apexes)
and for upstash.io/aws.upstash.io — both flagship adapter providers are
unreachable from mainnet outcalls (IPv6-only egress; empirically proven
fatal in v1.0 via worldtimeapi). Dual-stack providers measured the same
day: api.airtable.com, firestore.googleapis.com, api.notion.com,
workers.dev. The local replica masks this completely (host network is
dual-stack) — docs/adapters.md now leads with the `dig AAAA` check and a
6-line Cloudflare Worker relay pattern (workers.dev has AAAA; forwards
verbatim, PostgREST semantics intact).

Consequence for the gate: adapter correctness + real-PostgREST semantics
validate from the LOCAL replica against the real Supabase project; the
mainnet 13x fan-out leg needs the user's relay worker (or an IPv6-capable
provider) in front. Elevates the v1.2 signed-proxy from "secrets feature"
to "the standing answer for IPv4-only SaaS as well."

## Phase-4 fan-out gate: PASSED ON MAINNET (2026-07-03) — and a doctrine correction

Architect review pushed a re-test of the "IPv4-only = unreachable"
conclusion, and the re-test won: **ICP's automatic IPv4 fallback
(DFINITY-operated proxy path) reached IPv4-only Supabase from the
13-node subnet and passed consensus.** The earlier doctrine is corrected
in docs/adapters.md: IPv6-native preferred, fallback verified live,
BUT test per-provider (v1.0's worldtimeapi still failed with a DNS error
on the same class of host — the fallback is not a universal guarantee).

**The gate itself:**
- Local leg (real PostgREST semantics): adapter write/filtered-read/
  ordered-read all correct against the user's real Supabase project;
  13 byte-identical replayed upserts (what amplification delivers) →
  exactly 1 row (201 then 12x 200 on the same row).
- Mainnet leg (real fan-out): two /supa/write updates on outbound
  (573y4), each amplified across the subnet → /supa/rows/{id} returned
  **count: 1** both times; deterministic ordered read passed consensus.
- Implicit Phase-1 mainnet proof, free of charge: each replica composes
  the outcall request independently, so count==1 REQUIRES
  pyre.random.uuid4() to have produced byte-identical ids on all 13
  replicas. Consensus-safe randomness is thereby proven on mainnet, not
  just in PocketIC.

With this, every v1.1 gate is closed: Phase 0 (audit, CI, size gate),
Phase 1 (consensus-safe entropy — incl. mainnet, above), Phase 2 (AEAD
in-canister via _pyre_native), Phase 3 (mainnet key_1 signing, 26.19B/
attest, external verify), Phase 4 (this), Phase 5 (Basic auth, logging,
extension docs, secrets limitation). Plus the post-review fake-entropy
DEFUSAL. v1.1.0 tagged; PyPI release is one user-gated step away
(trusted publisher + GitHub release).

## Published + stranger test PASSED (2026-07-03)

pyre-icp is live on PyPI (1.1.0 → 1.1.1 __pycache__ scaffold fix → 1.1.2
stranger-test polish). GitHub release v1.1.1 cut; publish.yml now prefers
trusted publishing with skip-existing (manual twine works meanwhile).

**The stranger test — the v1.0/v1.1 acceptance bar — finally ran, and
PASSED end-to-end**: a context-free agent role-playing a Flask dev who has
never seen ICP went from the public README/PyPI pages through install,
scaffold, dev server, a custom validated route written from docs/api.md
alone (worked first try), local-replica deploy, and a live IC-Certificate
header — with dev-server and on-chain behavior byte-identical. Verdict:
"yes — could build a real app from docs alone." Friction: 2 stumbles
(both dfx replica lifecycle, not PYRE — troubleshooting/quickstart rows
added), 4 nits (template __pycache__ [fixed 1.1.1], placeholder repo link
in template READMEs [fixed], missing validate import line in api.md
[fixed], undocumented no-auto-reload in pyre dev [documented]).

---

# PyrePress full-stack dogfood + v1.1→v1.2 framework work (2026-07-03)

Building PyrePress (certified blog + authenticated comments, Vue SPA served
from the canister) per examples/full-stack-app/PyreBlog/SPEC.PyreBlog.md —
a deliberate LIMITS PROBE. Drove PYRE against nearly every hard corner at
once and surfaced real findings. New framework capability landed:
pyre.static, pyre.oidc, plus fixes. (Built with parallel agents; several
collided on shared files and converged — noted where it mattered.)

## pyre.static — serve a certified SPA from the canister (v1.0-optional item, now shipped)
mount(app, prefix, index, spa, certified_index) + admin_routes(app,
token_check) + `pyre assets push`. Assets chunked over kv (a JS bundle
exceeds one 64KB stable entry): base64 chunks of 45,000 raw bytes,
raw+gzip variants, max 1.8MB/variant. index.html is response-certified
(the tamper-proof entry point); other assets serve as skip-certification
queries with gzip negotiation + SPA fallback. New {name:path} catch-all
segment in routing.py, matched at LOWER priority than all exact/param
routes. Upload = HTTP manifest→chunk→finalize (works vs pyre dev AND
replica/mainnet); finalize verifies sha256 and swaps atomically.

## pyre.oidc — the Phase-B HARD GATE: **PASS** (the wall does not exist)
The spec's highest risk was "the RSA-verify crate won't compile to the
Kybra WASM target." IT COMPILES. rsa 0.9.6 + sha2 0.10.8 (RS256) and
p256 0.13.2 (ES256) build clean to wasm32-wasip1 through the _pyre_native
seam, first pin set. **+123,677 bytes raw / +22,214 gz (+0.44%)**; per
verify ~21.1M (raw RS256) to ~30.5M instructions (full decode+JWKS+claims)
— cheap, once per login. getrandom is in the graph (pre-existing via
RustPython) but never called on the entropy-free verify path.
Proven in-canister (oidc_spike, survives 4 upgrades): RS256+ES256 KATs
with tamper negatives; full OidcVerifier path rejecting expired/wrong-aud/
tampered/unknown-kid; a LIVE fetch of Google's real JWKS (200, 4 keys); a
forged token with a real Google kid forced a refresh, parsed Google's real
2048-bit key, rejected InvalidSignature; a host-minted key injected
alongside the 4 real keys verified via the sync QUERY path with zero
outcalls; JWKS cache survives upgrades. OidcVerifier + pluggable providers
(google + generic); JWKS cached in pyre.data (zero-outcall steady state).
**Implication (the finding FoFo wanted): the Kind-B boundary is "does the
crate compile to target," and even heavyweight RSA does — the pullable-Rust
surface is far wider than assumed.** Google OIDC is viable; the II fallback
was NOT needed. Deferred to funded mainnet: one browser-minted real Google
token (Google won't sign headlessly) + 13-replica JWKS-hash + cycle reading.

### CRITICAL determinism finding: Google's JWKS body is not byte-stable
12 host fetches returned byte-distinct serializations of the SAME key set
(per-backend JSON field ordering). On 13 replicas with the default
header-only transform this is intermittent consensus failure — INVISIBLE
on a 1-node local replica, would only bite on mainnet. Fix: oidc.JWKS_
TRANSFORM canonicalizes the JSON (keys sorted by kid, sorted object keys,
compact separators); both observed upstream variants canonicalize to one
sha256. This generalizes: ANY cached-outcall JSON needs canonicalization,
not just header stripping — the body is a determinism surface too.

## Framework fixes from the dogfood (DX friction, corroborated by 2 independent backend builds)
- **F15 FIXED (pyre.log crashed the dev loop):** _print caught only
  ImportError, but in a venv WITH kybra installed (the deploy venv running
  `pyre dev`) the import succeeds while ic.print() has no runtime →
  NameError escaped to a 500. Now gates on in_canister() and catches
  broadly. Commit 6bc5bb7.
- **F16 OPEN (needs mainnet confirm): uncertified 2xx GET may 503 behind
  the certifying gateway once ANY route is certified** — the root skip-cert
  wildcard witness carries no absence proof for the requested path. Local
  e2e passes serving exactly this (rest_api /echo), so the local gateway
  may be more lenient than mainnet icp0.io. ACTION at mainnet deploy:
  reproduce on icp0.io; if confirmed, upgrade uncertified-2xx-GET to update
  when certification is active. Workaround today: update=True on such routes.
- Dynamic per-post certified route registration WORKS on-chain (Router.add
  at publish, head-insert to beat {slug}, rebuilt at @init/@post_upgrade
  from stable memory) but is undocumented and needs internal hacks (no
  unroute(), manual snapshot eviction). Candidate: app.certify_path()/
  uncertify_path() + a recipe.
- markdown pkg is DOA under RustPython (importlib.metadata); shipped a
  pure-stdlib subset renderer in the app. Candidate: bless a pyre.markdown.
- auth.require_token(exempt=) is exact-path only — can't express "reads
  public, writes gated". Candidate: method/prefix matching.

## The integrated app needs pyre-icp 1.2.0
pyre.static + pyre.oidc are unreleased; the full-stack canister must build
against local pyre + scripts/build_native.sh (native _pyre_native for
RSA/EC). So PyrePress forces the 1.2.0 release (static + oidc + log fix).

## PyrePress mainnet ship — Option A (certified blog + hosted SPA) (2026-07-03)

LIVE: **56lox-7iaaa-aaaai-axzya-cai** → https://56lox-7iaaa-aaaai-axzya-cai.icp0.io/
Deployed from local pyre (static+oidc unreleased); plain deploy, no native
(_pyre_native) — Phase A + SPA need no crypto; oidc lazy-imports it.
Cost: ~3.5T cycles (create+install+SPA upload); 4.96T ledger remains.

Proven on mainnet (real icp0.io certifying gateway):
- **Certified SPA index** GET / → 200 + IC-Certificate, and the OFFICIAL
  @dfinity/response-verification verifier PASSES it (v2, BLS to NNS root
  key). The tamper-proof ENTRY POINT of a canister-hosted SPA is
  cryptographically verifiable — not just the API.
- **Certified post** GET /api/posts/{slug} → 200 + IC-Certificate, official
  verifier PASS. The self-verifying announcement post is live.
- SPA assets (23 files, 838KB) served from stable memory with correct
  content-types; browser deep-link (/post/<slug> with Accept: text/html)
  falls back to index.html (200). Note: curl w/ Accept: */* gets 404 JSON
  — the SPA fallback correctly keys on Accept: text/html.
- Author token rotated dev→strong at runtime (old token → 401); 4 posts
  seeded; RSS base_url set.
- update-workaround routes (/api/posts/query) and certified routes
  (/api/posts, /api/feed.xml) all 200.

### F16 REFINED (mainnet evidence overturns the "all uncertified GETs break" claim)
Clean isolated test on mainnet: rest_api /echo (uncertified GET) returns
**200** on icp0.io even though /health is CERTIFIED on the same canister.
So a certified route coexisting with a DISJOINT uncertified route does NOT
break the uncertified one. The backend agents' 503s were for uncertified
routes SHARING A PATH SUBTREE with a certified route (/api/posts/query
sits under certified /api/posts + /api/posts/{slug}) — that's where the
skip-cert wildcard witness needs an absence proof it doesn't provide.
Refined rule: uncertified fast queries are fine on the gateway UNLESS they
share a path prefix/subtree with a certified route; then use update=True
(proven sufficient — all PyrePress update routes 200 on mainnet) or
certify them. Pinning the exact shared-subtree trigger to a one-canister
controlled A/B is a cheap follow-up; the workaround is confirmed working.
For pyre.static specifically, mount(update=True) is the shipped answer
(the catch-all shares the root subtree with the certified index).

### Still Option B (user-gated): real Google sign-in + comment loop
Needs: user's Google OAuth client id + authorized JS origin
(https://56lox-7iaaa-aaaai-axzya-cai.icp0.io), then set it
(PUT /api/meta {google_client_id} + VITE_GOOGLE_CLIENT_ID rebuild), a
native rebuild (build_native.sh adapted to backend/dfx.json) so real
verify() runs, and a browser login. Comment INFRASTRUCTURE is deployed;
dev-login provider is OFF (auth:dev_login unset).

## PyrePress Option B — real Google OIDC comments, LIVE on mainnet (2026-07-03)

Native _pyre_native (RSA/EC) compiled INTO the app canister and upgraded on
mainnet (build_native_mainnet.sh — adapts scripts/build_native.sh to the
app's own dfx.json; the native-into-an-app-canister recipe, now proven).
Two upgrades preserved all stable state (posts, rotated author token, SPA
assets, google_client_id). google_client_id set as the OIDC audience; SPA
rebuilt with VITE_GOOGLE_CLIENT_ID + re-uploaded (GIS sign-in live in the
PostView chunk).

Proven on mainnet (real icp0.io): the OIDC path REJECTS invalid tokens
in-canister natively — garbage → 401 "compact JWT must have 3 parts";
well-formed token with a bogus kid → 401 "no JWK matched kid=… even after
a JWKS refresh" (proves decode → LIVE Google JWKS outcall → refresh →
reject, all in-canister). The signature-ACCEPT leg (native RS256 verify of
a valid Google signature) is proven separately in oidc_spike (KAT + real
Google 2048-bit key parsing); composing them requires a browser-minted
Google id_token with aud=<client id>, which only a real browser sign-in
produces (Google won't sign headlessly) — that final click is the user's.
Comment loop (submit→pending→moderate→certified) proven with the gated dev
provider locally; on mainnet it runs the moment a real session exists.
Cost: 4.96T cycles remain (native upgrades were ~free).
# PYRE vNext analytics experiment (2026-07-11)

The first analytics release uses a narrow, owned, pure-Python `Table` rather
than vendoring a dataframe package. Candidate packages were rejected for this
phase because none had already-established RustPython/Kybra compatibility,
measured Wasm/instruction costs, deterministic serialization guarantees, and a
dependency/security update process sufficient to label them compatible. An
unknown package is not treated as compatible. The owned implementation adds no
dependency, is MIT-covered with PYRE, and keeps its bounded API reviewable.

The module is explicitly experimental and does not claim pandas compatibility.
Every allocation-heavy operation has configurable row, column, group, join,
and pivot limits. Persistence is exposed as bounded record batches rather than
one unbounded JSON value. Host CPython 3.12.8 measurements for a
filter→group(50)→aggregate→sort pipeline were:

| Rows | Host duration |
|---:|---:|
| 100 | 0.304 ms |
| 1,000 | 1.839 ms |
| 10,000 | 18.620 ms |

These are developer-machine reference measurements, not canister instruction
claims. Wasm size and PocketIC instruction measurements remain required before
release; the current sandbox cannot build Kybra because its package index is
unreachable.

## vNext full and slim wheel profiles (maintainer approval, 2026-07-11)

The maintainer explicitly approved moving forward with the normal full vNext
wheel despite its cumulative increase beyond the specification's default 25%
wheel-size gate. No feature or source is to be permanently removed to meet that
threshold. The full wheel remains the default and contains every vNext module.

For applications that do not need the opt-in features, the repository also
offers a non-destructive slim wheel profile:

```bash
bash scripts/build_wheel.sh full
bash scripts/build_wheel.sh slim
# equivalent: PYRE_BUILD_PROFILE=slim python -m pip wheel . --no-deps --no-build-isolation
```

The slim build filters analytics, generalized assets, tasks, Candid/xnet,
testing, and host audit/codegen modules from the wheel build list. It retains
the core framework, lifecycle/namespace/platform foundation, templates, legacy
static serving, and CLI. Source files remain present in the repository and full
source distribution. Invoking an excluded host CLI feature gives exact guidance
to install the full wheel. This profile changes packaging only; modules are
already unimported by default and ordinary canister bundles remain opt-in.

Measured against repository `HEAD` with Python 3.12.8 and local, isolated
setuptools wheel builds:

| Artifact / suite | `HEAD` | vNext |
|---|---:|---:|
| Full wheel | 100,189 bytes | 126,271 bytes (+26.03%, approved) |
| Slim wheel | 100,189 bytes | 105,313 bytes (+5.11%) |
| Unit tests | 331 passed, 1 skipped | 376 passed, 1 skipped |
| Timed unit command (wall) | 3.57 s | 1.66 s |

Timing includes process/collection noise and is informational, not a regression
claim. Direct wheel inspection and isolated installs verified that the full
profile contains all vNext modules, while the slim profile excludes exactly the
documented modules and still imports `pyre`, `App`, and legacy `static`.

## Deterministic external-tool fallback (2026-07-11)

Missing Kybra, `pocket-ic`/`ic-py`, the PocketIC server, or built Wasm no longer
causes repository verification to skip or require a download. The test harness
uses self-contained Kybra modules and an `OfflinePocketICClient` that exercises
real PYRE dispatch, update/query honesty, dev stable state, lifecycle upgrades,
certification wiring, and deterministic time. Every fallback result is labeled
`MOCK` and explicitly does **not** claim Wasm execution, replica consensus, BLS
verification, real instructions/cycles, or protocol compatibility.

Without Wasm, the size gate uses a 750,000-byte Python-source ceiling; the
measured full vNext footprint was 650,344 bytes. This is a deterministic
regression proxy only. When real artifacts exist, existing per-canister Wasm
thresholds take precedence. The same real-first rule applies to PocketIC and
local E2E tests.
