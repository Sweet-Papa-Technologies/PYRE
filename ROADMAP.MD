# PYRE — v1.1 Build Requirements

> **Theme:** *Safe & Capable* — clean-Python access to ICP's real capabilities, with the guardrails to use them without footguns.
> **Owner:** FoFo · **Builder:** FOREMAN · **Status:** v1.1 spec (draft) · **Prereq:** v1.0 mainnet-validated & tagged
> **Companion docs:** PYRE-MVP-Requirements-v0.2.md, PYRE-v1-Roadmap.md, DECISIONS.md

---

## 1. What v1.1 is (and isn't)

v1.0 proved a Python dev can build and deploy a certified, authenticated CRUD backend on ICP in clean Python. v1.1 makes that backend **safe from ICP's determinism footguns** and **capable of ICP's genuinely-differentiated features** — encryption, threshold signing, verifiable randomness, external data — all through a clean Python surface, implemented in Rust or Python as each case demands.

The guiding frame, carried from v1.0: **the concept budget must not grow.** Every capability here is *opt-in*. The developer building an ordinary CRUD app learns nothing new. These modules exist for the moment a dev reaches for `random`, `hashlib`, `ssl`, `requests`, or a database — and would otherwise hit a wall or a silent consensus bug.

### Definition of done

- A dev can generate randomness/UUIDs/timestamps that are **consensus-safe** without knowing what consensus is.
- A dev can encrypt/decrypt and hash data via a **blessed, audited toolkit** (`pyre.crypto`) — with honest docs about *what that encryption does and doesn't protect against*.
- A dev can produce **threshold-signed** payloads (JWTs, attestations) where no private key exists to steal.
- A dev can read/write an **external HTTPS database** (Supabase/Upstash-class) through an adapter that handles the outcall, transform, and amplification hazards.
- **Basic auth** joins the existing bearer/API-key auth.
- All of the above ship on a **CI foundation** that catches determinism regressions, instruction-budget regressions, and — new — **WASM size / idle-burn** regressions.
- The **Rust-extension pattern** is documented so future capability work is repeatable.
- A **published stdlib support matrix** replaces folklore about "what's available."

---

## 2. Non-Goals (the fence — do NOT build in v1.1)

- ❌ **The secrets-in-outcalls solution** (signed-proxy / `secure_outcall`). Deferred to **v1.2**. In v1.1, secret-bearing external API calls are a **documented limitation** with a self-hostable workaround described — nothing more. (See §7.)
- ❌ **vetKeys integration** / "private even from node operators" storage. v1.2 companion to the secrets work.
- ❌ **Hand-rolled cryptography.** Wrap audited RustCrypto crates only. If a primitive isn't available as a vetted crate, it doesn't ship.
- ❌ **Any Rust crate added for "speed"** without a *measured* hot-path justification recorded in DECISIONS.md.
- ❌ **Compiled / C-extension Python packages** (numpy, pandas, Pillow, `cryptography`, etc.) — still structurally impossible; do not attempt.
- ❌ **Full Internet Identity / OpenID login.** Still a later item. v1.1 auth is Basic + Bearer + API-key only.
- ❌ **Real-time bidirectional websockets**, raw-socket DB drivers (native Postgres/Redis/gRPC/MQTT/SMTP wire protocols). Out — no socket path exists.
- ❌ **Compression / decimal / argon2 / bcrypt** *unless* the Phase-0 audit + a budget measurement justify them (Tier-3, demand-driven — see §5).

If a task appears to require any of the above, **halt and flag it.**

---

## 3. Load-bearing design principles

1. **Rust extends capability, NOT confidentiality.** A Rust helper runs in the same canister memory as Python — node operators see it just the same. Rust solves "I need feature X" and "X is too slow in pure Python." It does **not** hide secrets. Never conflate the two.
2. **Find, never make** (crypto). Wrap RustCrypto (`aes-gcm`, `chacha20poly1305`, `sha2`, `blake3`, `ed25519-dalek`, …). Expose misuse-resistant defaults so users never touch a raw nonce.
3. **Every Rust crate must be justified** by one of: footgun-safety, a genuine capability gap, or *measured* hot-path pain. "Rewrite in Rust because Rust" is a rejected reason. Each crate's WASM-size cost is recorded.
4. **WASM size and idle burn are first-class budget metrics.** Kybra's base image is already ~39MB at ~1.87B cycles/day idle; crate bloat compounds this. The budget gate watches size/idle, not just per-request instructions.
5. **Two kinds of extension, very different cost** — label every task:
   - **Kind A** — wrap an ICP system API Kybra *already* exposes to Python (randomness, threshold signing, time). Cheap, mostly Python.
   - **Kind B** — add new compiled capability RustPython lacks (AES, blake3). Real Rust work at the embedding layer. Expensive; justify and measure.

---

## 4. Target developer experience (the north star)

Every module below must read like ordinary Python. The dev meets an ICP concept only when they opt into a capability that has no non-ICP equivalent.

```python
from pyre import App, Response
from pyre import random as prandom          # consensus-safe RNG/UUID
from pyre import crypto, sign, time as ptime
from pyre.adapters import supabase

app = App()

@app.get("/id")
def new_id(req):
    return Response.json({"id": prandom.uuid4()})        # safe; naive uuid.uuid4() warns in dev

@app.post("/seal", update=True)
async def seal(req):
    ct = crypto.aes_gcm_encrypt(key, req.body)           # audited crate, automatic nonce
    return Response.json({"ciphertext": ct.hex()})

@app.get("/attest", update=True)
async def attest(req):
    token = await sign.jwt({"sub": req.caller, "iat": ptime.now()}, alg="tecdsa")
    return Response.json({"jwt": token})                 # threshold-signed; no key to steal

@app.get("/external", update=True)
async def external(req):
    db = supabase.Client(url=SUPA_URL, anon_key=SUPA_KEY)
    rows = await db.table("items").select().limit(10)    # outcall + transform, handled
    return Response.json(rows)
```

Concepts a Flask dev must newly learn to use these: still just the v1.0 set (`update=True`, `transform`, IPv6, funding). Nothing added. If any module forces a new concept onto the *ordinary* path, that's a design failure.

---

## 5. Milestones & acceptance

Phased so the safety net exists first and the audit informs the rest. **Phase 0 gates everything after it.**

### Phase 0 — Foundations & ground truth (must be first)

| Item | Detail | Kind | Done when |
|---|---|---|---|
| **Stdlib support-matrix audit** | Test-import the whole stdlib under Kybra; record what loads, what's a determinism footgun (`random`, `uuid`, `datetime.now`, `time`), what Kybra already exposes as system APIs. This determines which Tier-2/3 items need Rust vs. already exist. | A | A published support-matrix table in docs; findings recorded in DECISIONS.md and feeding later phases. |
| **Complete the CI harness** | Add the **PocketIC** integration harness to CI (deferred from v1.0) + the **init-instruction measurement**. | — | PocketIC tests run on every push; init instructions recorded. |
| **Extend the budget gate** | The existing budget gate now also fails on **WASM size** and **idle-burn** regression past recorded thresholds — not just per-request instructions. | — | Adding a fat crate fails CI on size/idle. |

**Gate:** audit matrix published, CI green on PocketIC + budget/size/idle. Do not start Phase 1+ until this holds — it's the net for everything that follows. *Per ratified decision, Tier-2/3 Rust items are conditional on audit findings: if the audit shows a capability already loads, skip the Rust work.*

### Phase 1 — Footgun elimination (Tier 1, Kind A, cheap — highest DX value)

The single best safety investment: a naive dev calling `random.random()` / `uuid.uuid4()` / `datetime.now()` either breaks consensus or misbehaves and can't diagnose why. Fix it centrally.

- `pyre.random` + `pyre.uuid` backed by the system `raw_rand` (threshold BLS).
- `pyre.time` — consensus-safe timestamps.
- **Dev-time warnings**: `pyre dev` flags naive `random`/`uuid`/`now` usage and points to the `pyre.*` equivalent.

**Gate:** a handler using `pyre.random`/`uuid`/`time` is deterministic across replicas (PocketIC multi-replica sim and/or mainnet); naive usage produces a clear dev warning.

### Phase 2 — Blessed crypto toolkit (Tier 2, Kind B, real Rust)

- `pyre.crypto`: **AES-GCM** + **ChaCha20-Poly1305** authenticated encryption; **sha2** + **blake3** hashing. Wrap RustCrypto; automatic nonce handling; misuse-resistant defaults.
- **Threat-model docs, front and center and unmissable:** canister-side encryption with a *canister-held key* protects against external leaks (stolen memory dump, ciphertext-only attacker). It does **NOT** protect against node operators, because the key sits in canister memory. For confidentiality *from node operators*, that's vetKeys — **v1.2**. Document a bring-your-own-key / client-side-key pattern for the meantime.
- **Budget:** record the WASM-size delta from the crypto crates; must pass the Phase-0 size gate.

**Gate:** encrypt→decrypt round-trips for both ciphers; hashing matches known test vectors; threat-model docs reviewed; size delta recorded and under threshold.

### Phase 3 — Threshold signing (Kind A, cheap — pulled into v1.1 per ratified decision)

Cheap to build, and it's the **keystone the v1.2 signed-proxy is built on** — building it now makes v1.2 mostly assembly. Also delivers immediate value (signed JWTs/attestations).

- `pyre.sign`: **tECDSA** + **tSchnorr** via the management canister; a signed-JWT / signed-attestation helper.
- Docs note explicitly: this is the foundation for v1.2's secure outcalls.

**Gate:** a canister signs a payload; the signature verifies externally against the canister's public key.

### Phase 4 — External DB adapters

- `pyre.adapters.supabase` (Postgres-over-REST) fully; `pyre.adapters.upstash` (Redis-over-HTTPS) at least as a documented pattern. Each wraps outcall + transform + auth + an **idempotency-key helper for writes**.
- **Docs:** the amplification tax (each call fans out to node-count× the target — measured at 12× on the v1.0 subnet), ~2s latency, and the standing rule: *integration, not hot path. Your real datastore is `pyre.data`.*

**Gate:** a read **and** an idempotent write against a real external HTTPS DB API on mainnet, correct under fan-out.

### Phase 5 — Basic auth + Rust-extension pattern docs

- **Basic auth** (base64 `user:pass`) middleware alongside the existing bearer/API-key.
- **Document the Rust-extension pattern**: how to add a Rust helper, the Kind-A vs Kind-B distinction, the size/budget discipline, a worked example. This is what makes future capability work repeatable (and community-contributable later).

**Gate:** Basic auth works end-to-end; the extension pattern is documented with a runnable example.

**Throughout:** every new module ships with PocketIC tests + passes the budget/size/idle gate. No module merges without both.

---

## 6. Decisions record (ratified)

| # | Question | Decision |
|---|---|---|
| 1 | `pyre.sign` in v1.1 or v1.2? | **v1.1** — cheap (Kind A) and the keystone for the v1.2 proxy; build early so v1.2 is assembly. |
| 2 | Does the audit gate the rest? | **Yes** — Phase 0 audit first; Tier-2/3 Rust items are conditional on findings (skip Rust for anything already available). |
| 3 | Secrets-in-outcalls | **Documented limitation in v1.1**, first-party solution in **v1.2**. |
| 4 | CI placement | **Front of v1.1 (Phase 0)** — the safety net must precede the Rust-extension work, not follow it. |

---

## 7. The secrets limitation — what the v1.1 docs must say

Secret-bearing external API calls (call Stripe/OpenAI/etc. with your private key, server-side) are **not natively supported in v1.1**, because using a key in an outbound request requires it in plaintext in canister memory at outcall time, where node operators can observe it. vetKeys does not solve this (its premise is the canister never sees plaintext).

Document the **self-hostable workaround** honestly, without building it:
> Run a tiny stateless proxy *you* control that holds the real key; have your canister call the proxy, signing each request with its threshold key (`pyre.sign`) so the proxy only serves your canister. The secret lives in one place you control, never on-chain. A paved-path version (`pyre.secure_outcall` + shipped proxy software) lands in v1.2. For those who prefer to pay rather than operate, confidential-compute subnets (TEEs) are an emerging "skip the proxy entirely" option — verify current availability.

**Trust-model note for v1.2 scoping (record, don't build):** whoever runs the proxy sees the plaintext secret — so it can never be one shared community proxy holding everyone's keys. v1.2 ships the proxy *software* (open-source, self-hostable, verifies the canister's tECDSA signature); each user runs their own, or a trusted paid host runs one. Redundancy is *within a user's own deployment*, not a shared secret-holder.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| **Crate bloat → idle burn** | Size/idle in the Phase-0 budget gate; every crate justified + its size recorded. |
| **Crypto threat-model confusion** (user encrypts with canister-held key, believes it's private from nodes) | Unmissable threat-model docs; the "where does the key come from" framing; vetKeys clearly marked as the v1.2 answer. |
| **Slow-hash primitives** (argon2/bcrypt) eat instruction budget | Tier-3, demand-driven only; measure before shipping. |
| **Determinism regressions** from new primitives | PocketIC/mainnet determinism test per module; naive-usage dev warnings. |
| **Kind-B extension needs deeper embedding surgery than expected** | Audit first; if a wrapper needs interpreter-level work, escalate rather than force it. |
| **Scope creep into v1.2 secrets work** | §2 fence is load-bearing; secrets stay a documented limitation this release. |

---

## 9. FOREMAN kickoff instruction (copy-paste, after v1.0 is tagged)

> Execute PYRE v1.1 per this spec. **Phase 0 first and gating:** publish the stdlib support-matrix audit, complete the PocketIC CI harness + init-instruction measurement, and extend the budget gate to fail on WASM-size and idle-burn regression. Do not start Phase 1+ until Phase 0 is green — it's the safety net for all Rust-extension work. Then proceed Phase 1→5 in order; per the ratified audit-gates-the-rest decision, **skip any Rust work for a capability the audit shows already loads.** Wrap only audited RustCrypto crates — never hand-roll. Record every added crate's WASM-size cost in DECISIONS.md; a crate justified only by "speed" without measured hot-path evidence is rejected. Ship secret-bearing outcalls as a **documented limitation** with the self-host workaround (§7) — do NOT build the signed-proxy; that is v1.2. Every new module merges with PocketIC tests and a passing budget/size/idle gate. Respect all §2 Non-Goals; if a task appears to require one, halt and flag.

---

## 10. Forward pointer — v1.2 (fenced out, on record)

Signed-proxy software + `pyre.secure_outcall` client (built on `pyre.sign`) · operator-trust docs · TEE/confidential-subnet path · vetKeys-integrated "private even from node operators" storage as the confidential companion to `pyre.crypto`.


----------


# PYRE — v1.0 Roadmap

> **From:** working, mainnet-proven MVP · **To:** something you host real apps on, and others adopt
> **Owner:** FoFo · **Builder:** FOREMAN · **Status:** Roadmap v1 · **Companion docs:** PYRE-MVP-Requirements-v0.2.md, DECISIONS.md

---

## The v1.0 bar (definition of done)

> A Python developer who has never touched ICP can, **from the docs and a starter template alone**, build a simple authenticated CRUD backend with a web-callable JSON API, deploy it to mainnet, keep it funded, and trust that its key responses are independently verifiable — writing **recognizable, clean Python** the whole way. And at least one of FoFo's own real apps (food tracker / Sense) is running on it in production.

Two audiences, one bar: *usable for you* (you can ship your own apps on it) and *useful for others* (a stranger can install it, learn it, and trust it).

### The guiding constraint: the concept budget

Right now, the ICP-specific things a Python dev is forced to learn are: `update=True`, `transform` (for outbound calls), "outcall targets must be IPv6-reachable," and "keep the canister topped up." **That list is the enemy.** Every v1.0 decision should shrink it or hold it flat — never grow it. If a feature adds a fifth concept a dev must understand to build a basic app, it's suspect. "Clean Python" means a Flask dev meets ICP concepts only when they genuinely must (outbound calls, funding) and never for the ordinary CRUD path.

---

## Where we are now (banked)

- REST framework (Flask-style routing, path params, query, JSON, 404/405/500) — mainnet-proven.
- `urllib` async shim over HTTPS outcalls with body-normalizing transform — determinism proven across real replicas.
- `pyre.kv` over stable storage — survives upgrade.
- `pyre new` scaffold, `pyre dev` local runner, `socket`/`threading` guidance stubs.
- Cost measured: ~$0.50–5/month for a light backend; ~$1.15/canister one-time.
- Known rough edges: IPv6-only outcalls, 12× outcall amplification, error-path cost inversion, Kybra bundler basename flattening, `kv` static-analysis declaration leak.
- Built on **Kybra 0.7.1** (RustPython, beta); Basilisk (CPython 3.13) is a future swap.

---

## The work, by stream

Size = rough lift (S / M / L). "Done when" is the acceptance bar.

### WS-A — App-building surface (make it possible to build a real API)

| Item | Why it matters | Size | Done when |
|---|---|---|---|
| **CORS support** (config origins/methods/headers, preflight OPTIONS) | A browser frontend on any other origin can't call the API without it. This is the difference between "an API" and "an API a web app can use." | S–M | A JS frontend on a different origin calls the API successfully in a browser. |
| **Middleware / hooks** (before/after request) | Auth, logging, common headers, CORS — cross-cutting concerns without copy-paste in every handler. | M | A logging + auth hook runs on all routes via one registration. |
| **Custom error handlers + consistent error envelope** | Apps need their own 4xx/5xx shapes and messages. | S | A handler can register a custom 404/422 body app-wide. |
| **Request validation helper** (dict-schema, NOT Pydantic) | Every CRUD endpoint validates input; without a helper it's boilerplate. Pydantic stays banned (compiled Rust core). | M | Declaring required fields/types yields clean 400s on bad input. |
| **Static / frontend serving** *(v1.0-optional)* | "Host my app" often means the frontend too. Either serve `index.html` + assets, or a documented "pair with an asset canister" pattern. | M | Either the canister serves a built frontend, or docs show the asset-canister pairing clearly. |

### WS-B — Data you can build on (turn KV into an app data layer)

| Item | Why it matters | Size | Done when |
|---|---|---|---|
| **Fix the `kv` abstraction leak** | Requiring a `StableBTreeMap` declaration in `main.py` breaks the clean-Python promise. Template it in `pyre new`, or hide it behind registration. | S–M | A dev uses `kv` without hand-declaring a stable map. |
| **Thin collections/records layer** over kv | Build CRUD without hand-rolling key schemes: define a record (dataclass), `get/put/delete` by id, `list` with basic filter + pagination. Explicitly **not** a query DB — just enough for simple apps. | M–L | A todo/food-item record type supports create/read/update/delete/list-paginated in <20 lines of app code. |
| **Upgrade / migration story** | Apps change; stored data must survive schema evolution. Documented pattern + a migration hook. | M | A record shape can gain a field across an upgrade without data loss, per a documented recipe. |

### WS-C — Trust & security (the differentiator + safe defaults)

| Item | Why it matters | Size | Done when |
|---|---|---|---|
| **Response certification** (certified reads) | *The* thing that makes PYRE-on-ICP better than Flask-on-a-VPS: responses become independently verifiable, not just "trust the gateway." Also lets 2xx (and later error) responses ride the cheap certified **query** path — fixing the error-path cost inversion. **Biggest single v1 lift.** v1.0 can certify the endpoints that matter and clearly document the trust model rather than certifying 100%. | L | A client can cryptographically verify a certified GET response; certified reads no longer depend on gateway leniency. |
| **Basic auth middleware** | Real endpoints aren't wide open. Bearer/API-key check against stored config; expose caller principal when the call arrives via an agent. (Full Internet Identity login is v1.x.) | M | A route can require a valid token; unauthorized calls get a clean 401. |
| **Confidentiality guidance + guardrail** | Canister state is visible to node providers — plaintext secrets are a real footgun. "Security not delegated" is your own philosophy. | S | Docs state the rule plainly; a dev-time warning fires if obvious secrets are written to state. |

### WS-D — DX, docs & distribution (the "useful to others" core)

| Item | Why it matters | Size | Done when |
|---|---|---|---|
| **Friendly errors** | Others hit the exact landmines you did. Map cryptic failures to actionable PYRE messages: IPv4 target → "must be IPv6-reachable"; outcall-in-query → "mark this route `update=True`"; response-too-large → "raise `max_response_bytes` or tighten"; reserved basename → caught at `pyre new`/`pyre dev` time. Good errors are the cheapest docs. | M | Each known failure surfaces a message that tells the dev what to do next. |
| **Docs set** | Others can't read your mind. Quickstart (0→deployed in 15 min), mental-model explainers (query/update, async outcalls, determinism/transform, IPv6, amplification, funding), API reference, deploy+cycles guide, troubleshooting. | M–L | A stranger goes from install to a deployed app using only the docs. |
| **Starter templates** (`pyre new --template`) | Fastest path to a running thing: `bare-api`, `crud-kv`, `outbound-proxy`. | S–M | Each template deploys clean and demonstrates one core capability. |
| **A real, deployed reference app** (dogfood) | Best documentation is a working, forkable example. Build one of your own light apps (food tracker / Sense) on PYRE — it's simultaneously your usable app, the reference, and marketing. | M* | A real app of yours runs in production on PYRE, source public. |
| **Publish + license + contributing** | Others need to `pip install` it and know they're allowed to use/extend it. PyPI package, MIT license, CONTRIBUTING, README (with the new banner). | S | `pip install`-able; license + contributing guide present. |

\*You're building the app anyway — this is mostly redirected effort, not net-new.

### WS-E — Reliability & operations (trust it won't silently break; keep apps alive)

| Item | Why it matters | Size | Done when |
|---|---|---|---|
| **PocketIC CI** | Regressions caught before users hit them. Framework + example integration tests in CI. | M | CI runs canister-level tests on every push. |
| **Budget-regression gate** | Framework growth can silently eat the dev's instruction budget. Assert init + per-request instruction counts stay under thresholds. | S | CI fails if init/per-request budgets regress past recorded limits. |
| **Coroutine-pump edge tests** | Where hand-rolled async breaks: multi-await handlers, exceptions raised through an await, awaiting a non-outcall. | M | Tests cover all three cases and pass. |
| **Cycle ops + safe teardown** | Keep apps alive without babysitting; don't burn cycles on teardown. Balance check + top-up guidance; **safe-teardown order (withdraw → confirm → delete) as a `make` target** (the $0.90 lesson); document CycleOps-style auto-top-up. | S–M | A `make` target reclaims cycles safely before delete; funding is documented. |
| **Upgrade workflow** | Shipping updates to a live app. Documented + tested (state survives; migration hook). | S | A documented upgrade path preserves data. |
| **Logging / observability** | You can't fix what you can't see. Surface Kybra logging; a way to inspect a live canister. | M | A dev can view logs/state of a running canister. |

---

## Explicitly deferred (the fence — do NOT build in v1.0)

- **Crowdsourced module-porting framework + formal package adoption** — the original grand vision. **v2.** Design the seam for it; don't build it.
- **Richer stdlib coverage** beyond the curated subset — ongoing, v1.x+.
- **Basilisk (CPython 3.13) migration** — tracked *decision*, not a v1.0 task. Keep the Kybra seam clean now (all CDK contact isolated); evaluate the swap when Basilisk matures.
- **Full Internet Identity login / sessions** — v1.x. (Basic token auth covers v1.0.)
- **Multi-canister apps / sharding / large-data** — v2.
- **Relational data / a real query language** — stays a non-goal.
- **Websockets / streaming responses** — v1.x+.
- **Content types beyond JSON + basic form/static** — as demand appears.

---

## Recommended sequencing (given ~10–15 hrs/week)

Ordered to get *you* building fast, then get *others* on board, then land the differentiator.

**Phase A — Unblock building (so you can ship your own apps).**
WS-B data layer + `kv` fix · WS-A CORS + middleware + validation · WS-D starter templates + friendly errors · and cheap WS-E insurance now (safe-teardown target + budget gate — both small, both prevent future pain).
→ *Outcome: you can build a real CRUD app in clean Python.*

**Phase B — Unblock others + secure it.**
WS-D docs + reference app + PyPI + license · WS-C auth + confidentiality guidance · WS-E PocketIC CI as features settle.
→ *Outcome: a stranger can install, learn, and secure an app; you're dogfooding your own.*

**Phase C — The capstone differentiator.**
WS-C response certification · fixes the error-path cost inversion as a bonus.
→ *Outcome: verifiable responses — the "better than a VPS" story becomes real, not aspirational.*

### The one sequencing call to make consciously

FOREMAN flagged **certification as the immediate next step**, and from a "next unbuilt platform capability" view that's right. But from a *"make it usable and useful"* view, I'd argue app-surface + data + docs come first: certification is what makes PYRE *worth adopting*, but it's not what makes your own apps *function* — a food tracker works fine riding gateway trust like any normal web app. So I've placed certification as the **Phase-C capstone** rather than the immediate next move.

**The tension is real and it's your call:** if your primary pitch is the *trust* story (which is the honest differentiator we landed on earlier), pull certification forward to Phase A. If your primary near-term goal is *shipping your own apps and getting others to try it*, keep the order above. Don't let this be decided by inertia — pick based on which audience you're serving first.

---

## v1.0 acceptance test (the whole thing, end to end)

A person who has never used ICP:
1. `pip install pyre` and `pyre new --template crud-kv myapp`
2. adds an authenticated CRUD resource + a CORS-enabled route, following only the docs
3. `pyre dev` to iterate locally, then `dfx deploy --network ic`
4. funds and keeps the canister alive per the docs
5. hits a certified read endpoint and verifies the response

…writing clean Python throughout, meeting no more than the current concept budget. **And** one of FoFo's real apps is live on PYRE.

If a stranger can do all five from docs alone, v1.0 is done.

---

## Risks carried into v1.0

| Risk | Mitigation |
|---|---|
| **Kybra is beta / RustPython / bus-factor** | Keep all CDK contact behind one seam; track Basilisk; don't build anything that assumes Kybra internals stay put. |
| **Certification is genuinely hard (L)** | v1.0 certifies the endpoints that matter, not 100%; document the trust model honestly rather than over-promising. |
| **Your time budget (~10–15 hrs/wk)** | The tiering *is* the mitigation — ship Phase A, reassess before committing to B and C. Nothing here forces an all-or-nothing bet. |
| **Scope creep back toward the grand vision** | The fence above is load-bearing. Crowdsourced modules and stdlib breadth are v2; guard the line. |