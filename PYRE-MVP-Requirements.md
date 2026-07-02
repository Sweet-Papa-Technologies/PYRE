# PYRE — MVP Build Requirements

> **Codename:** PYRE — *Python Runtime for the Edge* (name locked, see DECISIONS)
> **Owner:** FoFo · **Builder:** FOREMAN · **Status:** v0.2 (revised after Gemini 3.1 Pro review) · **Target:** Internet Computer (ICP)
> **One-liner:** Let a developer write recognizable Python — a small REST app plus an outbound HTTP call — and deploy it to a decentralized WASM host, without learning a new language.

---

## CHANGELOG v0.1 → v0.2

1. **Open questions resolved and locked** (§11 is now a decisions record): async-honest urllib, Flask-style routing, name PYRE, Cloudflare parallel track killed.
2. **Phases reordered:** the HTTPS-outcall determinism spike is now **Phase 1**, *before* the REST framework. It is a go/no-go gate for the whole project.
3. **Cold-start / instruction-budget risk elevated to HIGH** and reframed with the correct ICP mechanism (canisters are not lambda-style; the real risks are init-budget blowout, per-message budget, and upgrade re-init). Phase 0 now includes mandatory instruction measurements.
4. **Cloudflare validation track replaced** with a `pyre dev` pure-Python local runner — validates the DX surface without a second platform, and graduates into a real deliverable.
5. **Pydantic explicitly added to Non-Goals** (Rust-compiled core violates pure-Python rule).

---

## 1. Why this exists (context for the build agents)

Cloud compute is metered per project and it adds up. ICP canisters are WASM modules that run on a decentralized replica network with a cycles-based cost model, which is an attractive "pay for compute, not for idle" story. The catch: ICP does not run a normal OS. No real sockets, no threads, deterministic execution enforced across replicas, and outbound HTTP works through a consensus-gated "HTTPS outcalls" mechanism rather than `socket`/`urllib` as written.

The bet PYRE tests: **can we hide enough of that behind a familiar Python surface that a developer never has to think about it for the 80% case?** This MVP does not try to prove the whole vision. It proves the two load-bearing pieces:

1. **Outbound:** a `urllib`-shaped call that survives ICP's determinism/consensus requirements. *(Now first — it's the kill-shot risk.)*
2. **Inbound:** a Python-authored REST API reachable over normal HTTP.

If both work and feel like Python, the thesis is alive. If they don't, we learned it cheaply.

---

## 2. Goal & Non-Goals

### 2.1 Goal (Definition of Done)

A developer can:

- Write a small Python app using the `pyre` REST framework (routes, path params, JSON in/out).
- Iterate locally with `pyre dev` (instant local server, no replica needed), then `dfx deploy` to a local replica and to ICP mainnet.
- `curl` a public URL and get their Python handler's response.
- From a handler, make an **outbound HTTPS request** using a `urllib`-compatible shim and use the response in the reply.
- Do all of the above **without hand-writing any Candid, Rust, or Motoko, and without touching the raw HTTPS-outcalls / transform-function machinery** for the common case.

The MVP is "done" when the two example apps in §7 run end-to-end on mainnet and pass the acceptance tests in §8.

### 2.2 Non-Goals (do NOT build these — scope fence for FOREMAN)

- ❌ C extensions / native modules — no `numpy`, `pandas`, `cryptography`-with-native. Pure Python only.
- ❌ **Pydantic** (its v2 core is compiled Rust — violates the pure-Python rule). Validation in the MVP is manual/dict-based.
- ❌ Full CPython stdlib. Only the curated subset in §6.3.
- ❌ The crowdsourced module-porting framework. (Later phase. Design for it, don't build it.)
- ❌ A new/bespoke language or a Python "dialect." If a real Python subset can't do it, we note the gap; we don't invent syntax.
- ❌ `socket` / raw TCP/UDP. Unsupported by the platform — see §5.
- ❌ Threads, multiprocessing, async event loops beyond what outcalls require.
- ❌ Auth/identity, multi-canister orchestration, sharding, streaming responses, websockets.
- ❌ A package registry or `pip` integration.
- ❌ Cloudflare Workers (or any second platform) as a validation target. DX validation happens via `pyre dev` (§4.2).

If a task seems to require any of the above, **stop and flag it** rather than improvising.

---

## 3. Architecture overview

```
   HTTP client (curl / browser)
            │  (normal HTTPS)
            ▼
   ICP HTTP gateway / boundary node
            │  (Candid: http_request / http_request_update)
            ▼
┌─────────────────────────────────────────────┐
│  PYRE canister (a single WASM module)         │
│                                               │
│   pyre REST layer  ──► routes to handler      │
│        │                                      │
│   Python runtime (via chosen ICP Python CDK)  │
│        │                                      │
│   pyre.compat.urllib  ──► HTTPS outcall +      │
│                           transform function  │
└─────────────────────────────────────────────┘
            │  (outbound, consensus-gated)
            ▼
   External API (https://…)
```

Four layers, bottom to top:

| Layer | What it is | Who owns it |
|---|---|---|
| **Runtime** | Python interpreter compiled to WASM, running inside the canister | The chosen ICP Python CDK (see §4) — we consume, not build |
| **Gateway adapter** | Implements ICP's `http_request` / `http_request_update` Candid interface; parses raw request into a `Request`, serializes `Response` | PYRE |
| **REST framework (`pyre`)** | Flask-flavored routing, path params, JSON helpers, query-vs-update mapping | PYRE |
| **`urllib` shim (`pyre.compat`)** | `urllib`-shaped API backed by HTTPS outcalls + transform | PYRE |

Plus one off-chain component:

| Component | What it is |
|---|---|
| **`pyre dev` local runner** | A tiny pure-Python HTTP server that hosts the same `App` object locally, mimicking the gateway adapter's Request/Response mapping and mocking `pyre.compat.urllib` with real (undeterminized) HTTP. For fast iteration and DX validation. Not a replica emulator — replica-accurate testing stays on PocketIC/dfx. |

---

## 4. Platform & tooling

### 4.1 Primary target: ICP via a Python CDK

**Primary target: Internet Computer, via a Python Canister Development Kit (CDK).** The prior research pointed at the Kybra lineage (Demergent Labs' Python CDK for ICP) and a newer successor effort. **These move fast — Phase 0's first task is to confirm the current, maintained CDK, its version, its supported Python subset, and its maintenance status before committing.** Do not hardcode a version from this doc; pin it at build time in `DECISIONS.md`.

**Inherited-limitation caution (per review):** using an existing CDK is the right MVP shortcut, but we inherit its bugs and ceilings. Keep the runtime layer thin and swappable; if the CDK's outcall bindings or interpreter lifecycle can't meet §5.4's budget requirements, escalate to FoFo with evidence rather than working around it silently.

### 4.2 DX validation: `pyre dev` (replaces the Cloudflare track)

v0.1 proposed validating the API surface on Cloudflare Python Workers in parallel. **Killed** — different runtime model (V8 isolates + Pyodide vs. standalone WASM canister), so success there proves little about ICP, and it splits FOREMAN's focus. Instead:

- Build `pyre dev`: run the developer's `app` behind a minimal local HTTP server (pure Python, stdlib-only on the host side), using the same `Request`/`Response` objects and routing code paths as the canister gateway adapter.
- `pyre.compat.urllib` in dev mode performs real HTTP without transforms, but **logs a warning showing what the default transform *would* strip**, so determinism surprises surface before deploy.
- This validates "does the API feel like Python" with zero extra platform surface — and unlike the Cloudflare track, it graduates into a permanent, genuinely useful DX feature instead of throwaway work.

---

## 5. Key constraints & design decisions

These are the ICP realities that will break a naive port. Each has a required PYRE response.

### 5.1 Determinism — the big one
Canister code runs on multiple replicas that must agree byte-for-byte. Anything nondeterministic (wall-clock time, RNG, and especially **the response to an outbound HTTP call**, which may differ per replica — timestamps, request-IDs, header ordering) must be normalized or consensus fails and the call errors.

- **Requirement:** every outbound call goes through a **transform function** that strips/normalizes nondeterministic parts of the upstream response (volatile headers like `Date`/`Set-Cookie`/request-id headers, and optionally body fields) so all replicas converge. `pyre.compat.urllib` MUST apply a sane `default_transform` unless overridden, and MUST document exactly what it strips.
- **This is the project's go/no-go gate and is now Phase 1** (§8).

### 5.2 Outbound HTTP is async + update-only — **DECIDED: async-honest**
`urllib.request.urlopen()` is synchronous and blocking. HTTPS outcalls are **asynchronous**, cost cycles, take multiple consensus rounds, and **can only run in an update call, never a query.**

- **Decision (locked, per FoFo + review):** the shim is **async-honest**: `await urllib.urlopen(...)`; handlers that make outcalls are `async def` and run in update context. No sync facade in the MVP — faking blocking calls on WASM requires stack-switching hacks that break easily, and modern Python devs are comfortable with `async/await`. Revisit a sync facade only if real DX demand appears post-MVP.

### 5.3 Query vs Update calls
Query calls: fast, read-only, no consensus, **no outcalls, no durable state writes.** Update calls: consensus-backed, can persist and make outcalls, slower, cost more.

- **Requirement:** `pyre` routes default to **query** execution. A route that writes durable state or makes an outbound call MUST be marked `update=True` (or auto-promoted when it uses `pyre.compat.urllib` or `pyre.kv` writes). The gateway adapter maps these onto `http_request` (query) and `http_request_update` (update) correctly, including the boundary-node "upgrade to update" signal.

### 5.4 Instruction budgets & interpreter lifecycle — **ELEVATED TO HIGH (per review, mechanism corrected)**

The review flagged interpreter boot cost as a High risk. Correct severity — but the mechanism on ICP is different from lambda-style serverless, and the difference dictates what we measure:

- **ICP canisters are long-lived actors, not per-request lambdas.** The WASM instance's heap persists between messages. The Python interpreter should boot **once**, at `init`/`post_upgrade`, and stay warm in the heap — NOT re-initialize per request. There is no per-request "cold start" in the Cloudflare/Lambda sense.
- **The three real risks are:**
  1. **Init-budget blowout:** `init`/`post_upgrade` has a (large but finite) instruction limit. Interpreter boot + framework import + app parse must fit inside it — or the canister can't even install/upgrade.
  2. **Per-message budget:** each request handler execution has its own instruction ceiling. Heavy pure-Python work (big JSON parses, regex storms) can trap mid-request.
  3. **Upgrade re-init:** every code upgrade re-pays the full init cost; a growing app could eventually make itself un-upgradable.
- **Requirements:**
  - Verify (Phase 0) that the chosen CDK initializes the interpreter once and keeps it warm between messages. If it re-initializes per request, that is a **disqualifying CDK defect** — escalate.
  - **Measure and record in `DECISIONS.md` (Phase 0, mandatory):** (a) instructions consumed by hello-world init, (b) instructions per simple request, (c) instructions per JSON-echo request — via `ic0.performance_counter` or PocketIC's instruction reporting. Flag if init exceeds ~50% of the platform init limit or a simple request exceeds ~10% of the per-message limit: that headroom is the app developer's budget, not ours to spend.
  - Re-run the measurement as a CI check so framework growth can't silently eat the budget.

### 5.5 Response-size & cycle limits on outcalls
HTTPS outcalls have a max response size and a cycle cost that scales with it.

- **Requirement:** `urlopen` exposes `max_response_bytes` (conservative default). Exceeding it raises a clear PYRE error, not a cryptic trap. Document the current platform ceiling (confirmed in Phase 0). Keep MVP payloads small.

### 5.6 No sockets, no threads, no filesystem
`socket`, `threading`, `multiprocessing`, and most of `os`/filesystem are unavailable.

- **Requirement:** these modules are **explicitly stubbed to raise `NotImplementedError` with a message pointing to the PYRE alternative** (e.g. `socket` → "use pyre.compat.urllib; raw sockets aren't available on ICP"). Silent partial support is worse than a clear failure.

### 5.7 State & persistence
Canister heap resets on upgrade; durable data must live in stable memory (the CDK exposes stable structures).

- **Requirement (MVP-minimal):** provide one tiny `pyre.kv` key-value helper backed by the CDK's stable storage, used by the POST example so we prove persistence survives an upgrade. Don't build a real DB.

---

## 6. Functional requirements

### 6.1 The `pyre` REST framework (inbound) — **Flavor locked: Flask-style**

Decorator routing, no type-driven magic, no Pydantic (see Non-Goals).

- `App()` with decorator routing: `@app.get`, `@app.post`, `@app.put`, `@app.delete`.
- Path params: `/items/{id}` → `req.path_params["id"]`.
- Query string parsing → `req.query`.
- `req.json()`, `req.body`, `req.headers`, `req.method`, `req.path`.
- `Response.json(obj, status=200, headers=...)`, `Response.text(...)`, raw `Response(body, status, headers)`.
- Per-route `update=True` flag; auto-promote to update if the handler touches `pyre.compat.urllib` or `pyre.kv` writes.
- Sane errors: unmatched route → 404 JSON; handler exception → 500 JSON with message (no stack leak in prod mode).
- Implements the ICP HTTP gateway Candid interface (`http_request` query + `http_request_update` update). **Pin the exact interface from the current ICP interface spec in Phase 0** — do not transcribe it from memory.

### 6.2 The `urllib` shim (outbound) — `pyre.compat.urllib_request`

- `urlopen(url, *, method="GET", data=None, headers=None, transform=default_transform, max_response_bytes=...)` → awaitable returning a response object with `.status`, `.read()`, `.headers`, `.json()`.
- Backed by the CDK's HTTPS-outcalls API. Applies `transform` for determinism (§5.1).
- Import path mirrors stdlib closely enough to be recognizable (`from pyre.compat import urllib_request as urllib`). **Do not** monkeypatch the real `urllib` in the MVP — explicit import, no hidden global shims.
- Clear, typed errors for: response-too-large, outcall-in-query-context, upstream non-2xx (opt-in raise), timeout/failure.
- Dev-mode behavior per §4.2 (real HTTP + transform warning log).

### 6.3 Curated stdlib subset (MVP)
Confirm which of these the chosen CDK already provides vs. which PYRE must supply/verify: `json`, `re`, `datetime` (note: `datetime.now()` inside a canister returns consensus time — document this), `base64`, `hashlib` (pure-python fallback if native unavailable), `collections`, `dataclasses`, `typing`, `math`, `urllib.parse` (parsing only). Everything else: assume unavailable until proven, and stub the dangerous ones (§5.6).

### 6.4 Developer tooling
- `pyre new <name>` project template producing a deployable skeleton.
- `pyre dev` local runner (§4.2).
- One-command local deploy against the `dfx` local replica; documented mainnet deploy path.
- README covering, in plain language: the query/update mental model, the async-outcall rule, the determinism/transform concept, and the interpreter-lifecycle/budget model (§5.4).

---

## 7. Target developer experience (the spec's north star)

**This is what "done" should feel like.** If the final DX diverges materially from these two files, stop and reconcile with FoFo.

**Example A — REST API (inbound + persistence):**
```python
from pyre import App, Request, Response
from pyre import kv

app = App()

@app.get("/health")
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})

@app.get("/echo/{name}")
def echo(req: Request) -> Response:
    return Response.json({"hello": req.path_params["name"]})

@app.post("/items")            # auto-promoted to update: it writes state
def create_item(req: Request) -> Response:
    body = req.json()
    kv.set(f"item:{body['id']}", body)
    return Response.json({"created": body}, status=201)

@app.get("/items/{id}")
def get_item(req: Request) -> Response:
    item = kv.get(f"item:{req.path_params['id']}")
    return Response.json(item) if item else Response.json({"error": "not found"}, status=404)
```

**Example B — outbound HTTP via the urllib shim (async-honest, locked):**
```python
from pyre import App, Response
from pyre.compat import urllib_request as urllib

app = App()

@app.get("/quote", update=True)          # outcalls require update context
async def quote(req):
    resp = await urllib.urlopen(
        "https://api.example.com/quote",
        transform=urllib.default_transform,   # strips nondeterministic headers
        max_response_bytes=8_192,
    )
    return Response.json({"upstream_status": resp.status, "data": resp.json()})
```

A developer who knows Flask should read both of these and understand them with zero ICP knowledge, except for two new concepts we must teach in the README: `update=True` and `transform`.

---

## 8. Milestones & acceptance criteria — **REORDERED: outcall spike before framework**

Each phase ends in something runnable and verifiable. Ship-and-iterate; don't batch.
**Do not begin Phase 2 until Phase 1's gate passes.**

**Phase 0 — Ground truth, skeleton, and budget measurements**
- ✅ Confirmed & pinned in `DECISIONS.md`: CDK + version + maintenance status, Python subset, HTTPS-outcall size/cost limits, exact `http_request` Candid interface.
- ✅ Verified: CDK initializes the interpreter once (init/post_upgrade), heap-warm between messages (§5.4). If not → escalate, do not proceed.
- ✅ Measured & recorded: init instructions, per-request instructions, JSON-echo instructions, with headroom assessment.
- ✅ Hello-world Python canister deploys to the local replica; `curl` returns 200 from Python code.
- *Accept:* `curl localhost.../health` → `{"status":"ok"}` + all `DECISIONS.md` entries filled with measured numbers.

**Phase 1 — HTTPS-outcall determinism spike (GO/NO-GO GATE)**
- ✅ Minimal harness (no framework): an update method that calls a real public HTTPS endpoint through the CDK's outcall API with a transform function.
- ✅ `default_transform` v0: strips volatile headers, normalizes ordering; documented strip-list.
- ✅ Determinism test: repeated calls produce byte-identical post-transform results; passes on local replica AND **mainnet**.
- ✅ Failure-mode notes: what happens with an un-transformed nondeterministic response (capture the actual error for the README).
- *Accept:* mainnet canister fetches a real endpoint deterministically via transform.
- **Gate:** if this cannot be made reliable, STOP. Report findings to FoFo; the platform choice gets reassessed before any framework code is written.

**Phase 2 — REST surface (inbound) + persistence**
- ✅ `pyre` routing, path params, query parsing, JSON in/out, 404/500 handling.
- ✅ Correct query/update mapping incl. auto-promotion and the boundary-node upgrade signal.
- ✅ `pyre.kv` over stable storage; state survives a canister upgrade.
- ✅ Wire the Phase-1 outcall harness into `pyre.compat.urllib_request` proper.
- *Accept:* Example A passes an e2e suite on the local replica, including POST-then-upgrade-then-GET proving persistence; Example B runs on local replica through the real shim.

**Phase 3 — DX & packaging**
- ✅ `pyre new` template; `pyre dev` local runner (§4.2); one-command local deploy; documented mainnet deploy.
- ✅ README with the query/update, async-outcall, determinism, and budget/lifecycle explainers.
- ✅ `socket`/`threading`/etc. stubs raise helpful errors.
- ✅ Budget-regression CI check (§5.4).
- *Accept:* a person who has never used ICP follows the README and gets both examples live on mainnet.

---

## 9. Testing & verification strategy

- **Unit:** `pyre` routing, request parsing, response serialization, transform logic — plain `pytest`, no replica.
- **Integration:** **PocketIC** (deterministic ICP test harness) for canister-level tests in CI — fast, deterministic, and it exposes instruction counts for the §5.4 budget checks.
- **E2E:** `dfx` local replica for the full HTTP-gateway path; mainnet smoke tests for outcalls (Phases 1 & 3).
- **Determinism gate (required):** repeated outcall runs assert byte-identical post-transform responses. A failure here is a release blocker — and in Phase 1, a project blocker.
- **Budget gate (required):** CI asserts init/per-request instruction counts stay under recorded thresholds.
- **Non-support gate:** assert `import socket; socket.socket()` raises the PYRE `NotImplementedError` with the guidance message.

---

## 10. Suggested repo structure

```
pyre/
  pyre/
    __init__.py          # App, Request, Response
    routing.py
    gateway.py           # http_request / http_request_update adapter + Candid
    kv.py                # stable-storage KV
    dev.py               # `pyre dev` local runner (host-side, stdlib-only)
    compat/
      urllib_request.py  # the shim
      _stubs.py          # socket/threading/etc. informative stubs
  templates/pyre-new/    # project skeleton for `pyre new`
  examples/
    rest_api/            # Example A
    outbound/            # Example B
  tests/
    unit/  integration/  e2e/  determinism/  budgets/
  dfx.json
  README.md
  DECISIONS.md           # Phase-0 pinned facts + measured budgets live here
```

---

## 11. Decisions record (formerly "Open questions") — LOCKED

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Sync-facade vs async-honest urllib | **Async-honest** | Honest about the platform; sync-faking on WASM needs fragile stack-switching hacks; `async/await` is table stakes for Python devs. Revisit facade post-MVP only on real demand. |
| 2 | Framework flavor | **Flask-style decorators** | FastAPI-style implies Pydantic; Pydantic v2 core is compiled Rust → violates pure-Python. Manual validation for MVP. |
| 3 | Parallel Cloudflare validation | **Killed** | Different runtime model proves nothing about ICP; splits focus. Replaced by `pyre dev` local runner (§4.2), which validates DX and ships as a real feature. |
| 4 | Name | **PYRE** | Fits the ecosystem, clean import: `from pyre import App`. |

Remaining Phase-0 pins (CDK choice/version, limits, Candid interface, measured budgets) land in `DECISIONS.md`.

---

## 12. Risks & the single biggest blocker

| Risk | Severity | Mitigation |
|---|---|---|
| **Determinism on outcalls** — replicas disagree, calls fail | **Highest** | Transform-first design; Phase 1 is a dedicated spike + go/no-go gate; determinism test as permanent release gate |
| **Instruction budgets / interpreter lifecycle** (init blowout, per-message ceiling, upgrade re-init) | **High** *(elevated per review)* | Phase-0 verification that the CDK keeps the interpreter heap-warm; mandatory measurements in `DECISIONS.md`; budget-regression CI gate |
| CDK maintenance / bus factor / inherited limits | High | Phase-0 confirm status; thin, swappable runtime layer; escalate (don't work around) disqualifying defects |
| Outcall size/cost surprises devs | Medium | Conservative defaults; clear typed errors; document limits |
| DX ends up not feeling like Python | Medium | §7 examples are the acceptance bar; `pyre dev` gives fast DX feedback loops |

**Single biggest blocker:** determinism of outbound HTTP responses across replicas (§5.1). If the transform story doesn't hold up cleanly, the "just use urllib" promise breaks, and that's the whole point. That's why it is now **Phase 1**, immediately after ground truth, with an explicit stop-and-reassess gate.

---

## 13. FOREMAN kickoff instruction (copy-paste)

> Execute Phase 0 of `PYRE-MVP-Requirements.md` exactly: pin the CDK and platform facts into `DECISIONS.md`, verify the interpreter is initialized once and heap-warm between messages, and record the instruction-budget measurements. Then immediately execute Phase 1 — the HTTPS-outcall determinism spike with a transform function, proven on local replica and mainnet. **Do not write any REST-framework code (Phase 2) until Phase 1's gate passes.** If Phase 1 cannot be made reliable, stop and report findings; do not improvise workarounds. Respect every Non-Goal in §2.2; if a task appears to require one, halt and flag it.
