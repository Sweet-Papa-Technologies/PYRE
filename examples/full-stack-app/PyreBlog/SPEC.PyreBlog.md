# PyrePress — Build Spec v0.2 (with comments)

> **What:** A certified, tamper-proof blog **with authenticated comments**, hosted on PYRE — Web3 properties, zero Web3 complexity for reader or writer.
> **Owner:** FoFo · **Builder:** FOREMAN · **Status:** Draft v0.2 (executive override: comments in scope now) · **Runs on:** PYRE v1.1.0 (`pip install pyre-icp`)
> **Codename:** PyrePress *(placeholder)* · **Companion:** the PYRE spec/roadmap set; DECISIONS.md
> **Change from v0.1:** comments moved into the now-scope; `pyre.auth.oidc` added as a gated framework build; explicit show-stopper "out" defined.

---

## 1. Why this app (and why comments now)

The dogfood: the first real thing built on PYRE from a clean `pip install`, by the person who built PYRE — to surface DX edges and stand up a self-demonstrating artifact (the PYRE announcement post, hosted on PYRE, with a verifiable "this post is untampered" link).

**Comments are now in scope by executive decision, deliberately, as a limits probe.** Authenticated comments force PYRE against nearly every hard corner of the platform simultaneously — a new Rust crypto capability, a determinism-sensitive outcall, crypto-strength entropy, consensus time, and the query/update split for auth. Building it teaches the ceiling. This spec is structured so that probe has a hard gate and a graceful fallback, so "we hit a wall" produces a *finding*, not a dead end.

Envelope fit stays clean: small text, read-dominated (certified queries), rare ~2s writes. Phase A depends on nothing unsolved; only the comment path reaches for new capability.

---

## 2. Goal (Definition of Done)

FoFo can `pip install pyre-icp`, scaffold PyrePress, publish Markdown posts, deploy to mainnet, serve certified reads a reader can verify — **and** a reader can sign in (Google OIDC, or the II fallback) and leave comments the author moderates. Sessions are cheap; login crypto is proven or the fallback is engaged. The announcement post is live and self-verifying, and FoFo's DX-stumble log exists.

**Always-true floor:** even if the auth probe fully walls, the certified author-only blog (Phase A) ships to mainnet. There is no outcome where nothing ships.

---

## 3. Non-Goals

- ❌ Image/media **hosting** — a canister isn't a file host; images are external URLs. Bake in from line one.
- ❌ Themes/templating engine, multi-author, drafts-workflow, scheduled publishing.
- ❌ The API-consolidating/caching outcall proxy (v1.2+ framework; pairs with the signed proxy).
- ❌ Federated comments, notifications, search-as-a-service, media pipeline.
- ❌ Threshold-signed **session tokens** on the login path (too expensive — see §6; use stored crypto-random sessions).

If a task appears to need one of these, halt and flag.

---

## 4. Build phases

Three phases. **Phase A always ships. Phase B is a hard gate. Phase C runs on whatever auth survives B.**

### Phase A — Certified author blog (the floor; blocked on nothing)

- **Content model** (`pyre.data`): Post = `slug`, `title`, `markdown`, `tags[]`, `published_at`, `updated_at`, `status`, `schema_version`. Upgrade-safe with a migration path.
- **Markdown → HTML in-canister** (pure-Python renderer). *Verify a pure-Python renderer is in the supported-stdlib matrix on day one*; if not, render client-side storing both, preferring server-side so the certified artifact is the rendered post.
- **Author auth:** existing **bearer token** on all write routes. No new auth.
- **Certified reads:** `GET /posts` (paginated, newest-first, tag-filter), `GET /posts/{slug}` (certified HTML+JSON with a visible "verify this post" affordance), `GET /feed.xml` (RSS/Atom). CORS for a separate frontend origin.
- **Analytics:** per-post view counts via a dedicated `POST /posts/{slug}/view` update (queries can't write state); no third-party trackers (on-canister analytics is itself a selling point). Keep it counters-only — no analytics creep.
- **Frontend:** minimal reading view + bearer-gated compose/edit view. `pyre new --template blog` starter so it doubles as a reusable template.

**Phase A acceptance:** deployed to mainnet; a real post published via bearer token; `GET /posts/{slug}` passes independent certification verification; list/tags/RSS/view-count all work and survive an upgrade; announcement post live and self-verifying.

### Phase B — `pyre.auth.oidc` spike **(HARD GATE / the "out")**

Build in PYRE **core**, not in the blog — it's a reusable framework capability. **Prove the linchpin in isolation before any comment code exists.**

- **New capability required:** verify an **RS256** (and ideally **ES256**) signature in-canister via a RustCrypto crate through the proven extension seam. RSA *verification* is entropy-free and deterministic (no `getrandom` needed — the entropy problem does not apply here).
- **Spike target:** in a bare canister, verify a **real Google ID token** against Google's **real JWKS** (fetched via outcall, cached in `pyre.data`, refreshed on `kid` miss). Reject tampered and expired tokens (expiry vs `pyre.time`).
- **Measure and record in DECISIONS.md:** does the crate compile clean to the Kybra WASM target? WASM-size delta (against the budget gate)? instruction cost per verify?

**THE GATE — trigger the "out" if any of these fail within a bounded effort:**
- the RSA-verify crate (or its deps) won't compile to the Kybra WASM target, **or**
- it blows the WASM-size or per-message instruction budget, **or**
- a real Google token can't be verified correctly (signature/claims) on mainnet.

**The "out" (tiered fallback — each step still delivers authenticated comments except the last):**
1. **Fall back to Internet Identity** for comment auth. II yields a verified principal with **no external RSA verification** — the platform/agent handles identity; the canister reads a verified `req.caller`. Trade-off: more web3-flavored login UX (II now supports Google sign-in under the hood). This de-risks the crypto entirely while keeping real, authenticated comments. **This is the primary out.**
2. If II integration also proves too heavy for this iteration → **ship Phase A alone**, defer comments, and record the wall as a real platform-limit finding (revisit under Basilisk/CPython, whose stdlib/crypto story may be gentler).

**Phase B acceptance (Google-OIDC path):** a real Google ID token verifies in-canister on mainnet; tampered/expired rejected; size delta passes the budget gate; the provider interface is documented with a second provider stubbed (pluggability proven).

### Phase C — Comments (thin layer on whichever auth survived B)

- **Sessions (cheap by design):** on successful login (Google-OIDC *or* II), issue a **stored session** — a crypto-random id from `await pyre.random.raw_bytes()` mapped to the verified identity in `pyre.data`. Session validation is a **read (query-fast)**. Do **not** threshold-sign sessions (see §6).
- `POST /posts/{slug}/comments` — authenticated submit; store `{author_identity, body, ts, status: pending}`. Body size-capped; rate-limited per identity.
- **Moderation:** author (bearer token) approves/rejects; only approved comments render.
- `GET /posts/{slug}/comments` — approved comments, **certified**.
- **Pluggable providers:** the auth interface takes Google/GitHub OIDC now, II now (as the fallback path), and **FFN later** (its SDK is JS today; a `pyre`-side FFN provider slots in when FFN is online) — additions, not rewrites.

**Phase C acceptance:** signed-in reader submits a comment; author moderates; approved comments render certified; unauthenticated submission refused; whole loop runs on mainnet.

---

## 5. External setup (real steps, easy to trip on)

- **Google OAuth client ID** (public — *not* a secret): register the canister's URL / custom domain as an **authorized JavaScript origin** in Google Cloud Console. The classic OAuth setup pain is an origin/redirect mismatch — get this right early.
- **Frontend:** Google Identity Services JS returns the ID token to the browser (public client, no secret). If the II fallback is engaged instead, the frontend uses the II auth-client.

---

## 6. Limits this build will teach (the point of the probe)

Concrete platform boundaries this exercise will surface and prove, recorded as you go:

- **The Kind-B extension boundary is "does this crate compile to the target."** RSA-verify is the test case; the gate result tells you how freely you can pull in arbitrary Rust crypto. This is the single most valuable thing you'll learn.
- **Threshold signing is too expensive for hot paths** (~$0.035/signature). Hence stored crypto-random sessions, not signed tokens. Signing is for rare, high-value attestations — not per-login, never per-request.
- **Auth flows are update-bound** (~2s): login and comment-submit go through consensus; only reads (posts, approved comments, session checks) stay query-fast. Fine for this workload; a real constraint to feel.
- **Caching collapses the amplification tax:** cache JWKS and a login does zero outcalls, so 13× fan-out to Google never happens in the steady state. General lesson: cache aggressively, outcall rarely.
- **Consensus time is enough for expiry, not for precision:** token `exp` checks are fine; don't expect sub-second time semantics.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **RSA-verify crate won't compile to the Kybra WASM target** | **Highest** — this is the wall if there is one | Spike in isolation FIRST (Phase B gate); II fallback if it fails |
| Pure-Python Markdown renderer not in the supported subset | Medium | Confirm against the stdlib matrix on day one; client-side fallback storing both |
| WASM size/idle growth from the RSA crate | Medium | Budget gate (size/idle) already guards it; record the delta; justify the crate |
| Comments = untrusted input + identity | Medium | Authenticated-only + moderation + per-identity rate-limit + size caps; never improvised auth |
| OAuth origin/redirect misconfig | Low-Med | Register authorized origins early (§5); test the login round-trip before building on it |
| Treating `pyre.auth.oidc` as "blog work" | Low | It's **framework** work in PYRE core; every future app benefits |

---

## 8. FOREMAN kickoff (copy-paste)

> Build PyrePress per this v0.2 spec, on the published `pyre-icp` (v1.1.0) — install as a user would (not from the local checkout) and log all friction.
> **Phase A first:** ship the certified author-only blog to mainnet (posts CRUD via bearer token, certified list/single/RSS reads with a visible "verify" affordance, tags, view-count analytics via an update endpoint, minimal frontend, `pyre new --template blog` starter). Confirm a certified read passes independent verification. **Phase A must ship regardless of what happens next.**
> **Phase B is a hard gate — do it in isolation before any comment code:** build `pyre.auth.oidc` in PYRE **core** by adding RS256/ES256 verification via the Rust extension seam, and verify a REAL Google ID token against Google's cached JWKS in a bare canister on mainnet, rejecting tampered/expired tokens. Record compile result, WASM-size delta, and per-verify instruction cost in DECISIONS.md. **If the crate won't compile to target, blows the budget, or can't verify a real token within a bounded effort, STOP the Google path and take the "out": fall back to Internet Identity for comment auth (verified principal, no external RSA verification). If II is also too heavy this iteration, ship Phase A alone and record the wall as a platform-limit finding.**
> **Phase C:** comments on whichever auth passed — stored crypto-random sessions (`pyre.random.raw_bytes` + `pyre.data`, NOT threshold-signed), authenticated submit, author moderation via bearer token, certified reads of approved comments, per-identity rate-limit, size caps.
> Respect all §3 Non-Goals; if a task appears to require one, halt and flag. Report the Phase-B gate result explicitly — it's the finding FoFo is after.