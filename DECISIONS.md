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
