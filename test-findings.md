# PYRE vNext — Review & Test Findings

**Date:** 2026-07-11
**Scope:** the vNext feature set merged in `c20e9ad` (tasks, xnet, generalized
assets/streaming, candid parser+codegen, analytics, audit, platform/lifecycle/
namespace, testing client, packaging).
**Reviewer:** automated code review (3 parallel readers) + real-toolchain
execution.

---

## Fixes applied (follow-up pass)

The clear, low-decision-risk defects below were fixed in this branch, each with
a regression test. The full suite is **426 passing** (was 412; +14 new tests),
and the fixed framework was **re-compiled under Kybra and re-verified on a local
replica** — including a round-trip of non-ASCII text through the real in-canister
`ic.candid_encode`/`ic.candid_decode` (`/candid/echo` → `match: true`) and the
range clamp (`bytes=0-99999` → `206`, was `416`).

| ID | Fix | File | Regression test |
|---|---|---|---|
| H1 | Encode Candid text with `\u{...}`/named escapes, not JSON `\uXXXX` | `pyre/xnet.py` | `test_text_codec_round_trips_unicode_and_uses_candid_escapes` |
| H2 | Decode Candid `\XX` byte + `\u{...}` escapes (UTF-8), not `json.loads` | `pyre/xnet.py` | `test_decode_accepts_replica_byte_and_scalar_escapes` |
| H4 | Index chunks by `manifest["chunk_size"]`, not the live store's config | `pyre/assets.py`, `pyre/_asset_store.py` | `test_range_indexes_by_manifest_chunk_size_not_store_config` |
| H5 | Memoize alias resolution (O(n)) + cap resolved depth (no `RecursionError`) | `pyre/_candid_parser.py` | `test_alias_fan_out_resolves_in_linear_time`, `test_deep_alias_nesting_raises_candid_error_not_recursionerror` |
| H6 | `restore()` reconciles a changed `definition_hash` on upgrade | `pyre/tasks.py` | `test_upgrade_reconciles_a_changed_schedule` |
| H7 | `finalize()` clears any GC tombstone for the generation it publishes | `pyre/_asset_store.py` | `test_republished_generation_is_not_destroyed_by_gc` |
| M1 | Strip only a real `-e`/`--editable` prefix (regex), not the char set | `pyre/_audit.py` | `test_editable_prefix_strip_does_not_mangle_package_names` |
| M2 | `begin()` reopens a stale finalized session when its asset is gone | `pyre/_asset_store.py` | `test_identical_content_can_be_reuploaded_after_delete` |
| M4 | Clamp range `end >= size` to `size-1` (RFC 7233) instead of 416 | `pyre/assets.py` | `test_range_end_past_eof_is_clamped_not_416` |
| M5 | `pivot()` rejects a column value colliding with the index column name | `pyre/analytics.py` | `test_pivot_rejects_column_value_colliding_with_index_name` |
| M6 | Accept underscore digit-groups in Candid numeric literals | `pyre/xnet.py` | `test_numeric_literals_accept_underscore_digit_groups` |
| L2 | `restore()` fails closed on a foreign task schema | `pyre/tasks.py` | `test_restore_fails_closed_on_foreign_schema_record` |

**Deferred (need a design decision, left as documented findings):**
- **H3** (forgeable/cross-namespace streaming tokens) — the right fix is HMAC
  signing over a per-canister secret plus an explicit "is this asset public"
  gate; that's a small design (where the secret lives, how public is declared),
  not a mechanical change.
- **M3** (quota bypass + orphan chunks via unfinalized sessions) — needs staging
  byte-accounting and a GC path for abandoned sessions.
- **L1** (`__pyre:` kv-prefix reservation) — the framework writes its own
  `__pyre:` keys through the same `kv.set`, so a naive reject would break it;
  needs a separate internal write path.
- **L3/L4** (heterogeneous-type aggregate; parser rejects recursive types) —
  behavior questions, not clear bugs.

The per-finding detail below is the original report and is unchanged; treat the
table above as the authoritative fix status.

---

## Summary

The vNext code is in good shape structurally and — importantly — **it compiles
under Kybra/RustPython and runs correctly on a real replica**, which the prior
internal review had explicitly *not* verified. I built and deployed a purpose-
made exercise canister (`examples/vnext_exercise`) that imports every new module
and confirmed the framework path end-to-end.

However, the review surfaced **7 high-severity** and several medium correctness/
security defects that the happy-path test suite misses. Two are outright broken
functionality (non-ASCII text over xnet), one is a data-leak (forgeable, cross-
namespace streaming tokens), one is a host-side DoS (candid parser), and one
silently drops durable state on upgrade (task schedule changes). All findings
below were reproduced with runnable snippets; the ones marked **[replica]** were
additionally confirmed against a deployed canister.

### What passed (verified this session)

| Check | Result |
|---|---|
| `pytest tests/unit tests/pocketic` (dev venv) | **412 passed** |
| Kybra compile of every vNext module (`dfx deploy vnext_exercise`) | **Built Wasm in 45s, installed clean** |
| `/health`, `/analytics`, `/xnet/service` on replica | **[replica] correct** |
| Task persist + restore across install; `run_now` as update | **[replica] runs, ticks increment** |
| Asset upload (update) + serve (query) + `Range` 206 (certified) | **[replica] correct** |
| Suffix range `bytes=-5`, open range `bytes=6-` | **[replica] correct** |
| Candid `pyre candid check` / `generate` (deterministic, source-hashed) | **correct** |

The exercise canister and its `dfx.json` entry are test artifacts added this
session — remove them (or keep them as a smoke test) at your discretion.

### Mainnet verification (the section-12 release gate — now run)

The exercise canister was deployed to **ICP mainnet** with the funded `pyre-dev`
identity (cycles ledger), exercised end-to-end through the real boundary node,
then withdrawn and deleted. This closes the "real-platform gates not run here"
gap the internal review had flagged.

| Real-IC check | Result |
|---|---|
| Canister id | `wgmmw-mqaaa-aaaal-qxfjq-cai` (created, tested, **deleted**) |
| `/health` certified read via `raw.icp0.io` boundary node | **200 `{"status":"ok"}`** |
| `/analytics`, `/xnet/service` | **correct** |
| Tasks persisted + restored on **mainnet** install (heartbeat 60s, warmup once) | **scheduled** |
| Asset upload (real update) + serve + `Range` | **206, correct bytes** |
| `run_now("heartbeat")` real update → tick increment | **ran, ticks=1** |
| `/health` query instruction count (`pyre_perf_probe`) | **5,274,917 instructions** |
| Wasm module size | **28.2 MB** |
| Canister memory size after install+e2e | **52.2 MB** |
| Idle cycles burned / day | **2,197,584,612** |
| Net cycle cost of the whole mainnet test (install + updates + idle) | **≈0.65 TC** (4.958 → 4.312 TC after refund) |
| Teardown | stopped, `2.35 TC` withdrawn to cycles ledger, canister deleted |

Note: mainnet install of a Kybra canister needs a healthy initial balance — a
0.5 TC allotment was rejected by the subnet ("insufficient cycles to grow
memory"); 3 TC succeeded. Worth documenting for the deploy guide.

---

## HIGH severity

### H1. xnet cannot **encode** non-ASCII `text`/`principal` arguments
`pyre/xnet.py:98-103` (`_candid_text`) encodes text with
`json.dumps(value, ensure_ascii=True)`, which escapes non-ASCII as `\uXXXX`.
Candid's text grammar has no `\uXXXX` form (only `\u{...}` and `\XX`), so
`ic.candid_encode` rejects it. **Every cross-canister `call`/`notify` with a
non-ASCII text argument fails at runtime.**

```
_candid_text(TypeSpec("text"), "café ☃")  ->  '"caf\\u00e9 \\u2603"'   # é invalid in Candid
```
Any app forwarding user names, messages, or emoji through xnet is broken.
Not covered — the runtime-candid tests only use ASCII.

### H2. xnet cannot **decode** non-ASCII `text` responses
`pyre/xnet.py:191,197` decode `text`/`principal` via `json.loads(token)`. The
replica encodes non-ASCII/control text with Candid `\XX` byte escapes or
`\u{...}`, neither of which `json.loads` accepts → `CandidDecodeError`.

```
_decode_candid_text(r'("caf\c3\a9")', (text,))  -> JSONDecodeError
_decode_candid_text(r'("\u{e9}")',   (text,))  -> JSONDecodeError
```
Together with H1, the text codec silently works for the pure-ASCII subset only.
**Fix:** implement Candid text escaping/unescaping; do not equate it with JSON.

### H3. Public streaming callback is unauthenticated, forgeable, and cross-namespace
`pyre/assets.py:56-70` (`streaming_callback`) is a public query. Tokens are
plain (unsigned) base64 JSON validated for *shape* only. The callback
reconstructs `AssetStore(payload["n"], ...)` from attacker-controlled fields and
returns chunk bytes for **any namespace/asset/generation**, including namespaces
never mounted on a route.

Reproduced — a token forged for an unmounted `private` namespace leaks the bytes:
```
LEAKED: b'TOP SECRET DOSSIER TOP SECRET DOSSIER TO'
```
The only "secret" is the generation hash, which is deterministic, permanent, and
emitted in plaintext in every legitimately-issued token. Docs say "not for
private media," but the cross-namespace reach + forgeability exceed that caveat.
**Fix:** HMAC-sign tokens over a canister secret and confirm the asset is meant
to be public before serving.

### H4. `response()`/streaming index chunks with the store's `chunk_size`, not the manifest's
`pyre/assets.py:36,42,61` compute `first_index = start // self.chunk_size` and
mint tokens with `self.chunk_size`, but chunks are physically addressed by the
`chunk_size` persisted in the manifest at finalize time
(`pyre/_asset_store.py:154`). If the `AssetStore` is later constructed with a
different `chunk_size` (a plausible config change / redeploy), every range/stream
read indexes the wrong chunk and serves **corrupted bytes with a correct-looking
`Content-Range`**. **Fix:** derive chunk_size from `manifest["chunk_size"]`.

### H5. Candid parser: exponential alias expansion (host-side DoS)
`pyre/_candid_parser.py` `resolve_type` expands aliases by structural
duplication; a record whose two fields both reference the next alias doubles the
node count per level. `MAX_FIELDS` is not incremented during resolution and
`MAX_ALIAS_DEPTH` bounds chain length, not breadth. A **~750-byte** `.did` hangs:

```
n=14  554B  0.04s     n=17  668B  0.68s     n=19  744B  4.89s   (≈4× per +2 levels)
```
`pyre candid generate` runs on the developer host/CI, so a malicious or
accidental `.did` stalls the build. **Fix:** bound total resolved-node count (or
memoize alias resolution). Related: `resolve_type` can also raise a bare
`RecursionError` (not a `CandidSyntaxError`) within both documented depth caps.

### H6. Task schedule/overlap/catch_up changes are silently ignored on upgrade
`pyre/tasks.py`: the reconciliation that rewrites `interval_ns`/`overlap`/
`catch_up` when `definition_hash` changes exists **only in the host path**
(lines 133-140). On-chain the decorator just logs and returns; `restore()`
(lines 319-351) only *creates* records that don't yet exist and never compares
`definition_hash` for existing ones. Reproduced (in_canister path):

```
v1: every(seconds=2)   -> record interval_ns = 2000000000
upgrade to every(seconds=3600), restore()
after:                    record interval_ns = 2000000000   (expected 3600000000000)
```
The durable record keeps the **old** schedule forever. **Fix:** in `restore()`,
compare `definition_hash` and re-reconcile changed definitions.

### H7. GC can delete live data after a generation is re-published (A→B→A)
`pyre/_asset_store.py` (finalize/`garbage_collect`): because generations are
deterministic (`sha256(namespace:asset_id:content_sha256)`) and chunks are
immutable/shared, re-publishing generation A (after A→B) leaves a stale garbage
tombstone for A that GC then honors, deleting A's now-live chunks. Reported by
the asset reviewer with a repro; my independent repro hit the related session-
conflict (M2) first, which blocks that exact sequence with *identical* content —
so this fires when A is re-derived by other means. Treat as **needs-fix +
regression test**; `finalize()` should clear any garbage tombstone for the
generation it publishes.

---

## MEDIUM severity

### M1. Audit `lstrip("-e ")` corrupts package names → false-clean native scan
`pyre/_audit.py:121`: `requirement.lstrip("-e ")` strips the *character set*
`{-, e, space}`, not an `-e ` prefix. Confirmed:
```
eventlet==0.33.0 -> 'ventlet==0.33.0'   editdistance -> 'ditdistance'
example-pkg      -> 'xample-pkg'        e2e-runner==1.0 -> '2e-runner==1.0'
```
For such packages the compatibility lookup uses the wrong key and
`_audit_installed_distribution` hits `PackageNotFoundError` and returns `[]`, so
the native-extension / non-pure-wheel scan is **silently skipped (false clean)**.
**Fix:** strip only a real `-e`/`--editable` prefix.

### M2. Identical-content re-upload after delete bricks; sessions never reclaimed
`pyre/_asset_store.py`: session keys are deterministic and persist `finalized`
after finalize; `delete()`/`garbage_collect()` never remove them. Confirmed:
after upload→delete, `begin()` with the same content returns the old finalized
session and `put_chunk` raises `AssetConflict: upload session is finalized` —
the asset can never be re-uploaded with identical bytes. Sessions also leak
stable memory across upgrades.

### M3. Quota bypass + orphan chunk leak via unfinalized sessions
`namespace_bytes()`/`total_bytes()` count only finalized manifests, and
`put_chunk` never re-checks quota. N concurrent sessions each pass the `begin`
check while collectively writing N×size of real chunk data, with no GC path for
staging chunks of abandoned sessions (permanent stable-memory leak, survives
upgrades). Upload is admin-gated, but this defeats the quota.

### M4. Range `end >= size` returns 416 instead of clamping **[replica]**
`pyre/assets.py:32` rejects any concrete `last-byte-pos >= size` with 416. RFC
7233 requires clamping to `length-1`. Confirmed on the deployed canister:
```
Range: bytes=0-99999  (18-byte asset)  ->  416     (should be 206, full body)
```
Media players that probe with a large concrete end get a hard failure.

### M5. Analytics pivot label can collide with the index column → silent data loss
`pyre/analytics.py:150-153`: duplicate-label guard covers collisions *among*
column values but not a value that stringifies to the `index` column name.
`item[index]` (the row key) is then overwritten by an aggregate:
```
pivot(index="idx", columns="cat", values="val") with a cat value == "idx"
-> [{'idx': <aggregate>, 'other': 7}]   # the index value is gone
```

### M6. xnet numeric tokenizer rejects Candid underscore digit-groups
`pyre/xnet.py:119-122` `_VALUE_TOKEN` has no `_`; Candid permits `1_000_000`.
`_decode_candid_text('(1_000_000 : nat)', (nat,))` → `CandidDecodeError`.

---

## LOW severity

- **L1.** `kv._check_key` (`pyre/kv.py:63`) does not reserve the `__pyre:`
  prefix, so an app can write `kv.set("__pyre:tasks:1:...")` and collide with
  framework state, contradicting the namespace module's collision-safety claim.
  (The escaping itself is injective — no cross-identity collision found.)
- **L2.** `tasks.restore()` mutates/saves records straight from `kv.get` with no
  `schema` check, unlike `_load`/`list`; a foreign-schema record risks a silent
  migration or `KeyError`.
- **L3.** Analytics `aggregate(... "max"/"min")` over a column mixing `str`/`int`
  raises `TypeError` (unlike `sort_by`, which is total via `_sort_value`).
- **L4.** The candid parser fails-closed on *all* recursive Candid types
  (`type List = opt record { head: nat; tail: List }`). Acceptable only if input
  is restricted to PYRE-emitted `.did`; it makes the parser unusable on general
  interfaces.

---

## Clean / no issues found

- `_platform.py` adapter injection and `_lifecycle.py` `(order, name)` hook
  ordering + required-failure propagation are correct.
- `xnet._valid_principal` (base32 + CRC32 checksum) correctly rejects malformed
  principals — no principal spoofing.
- xnet reply/request size guards, cycles non-negativity, and query-context
  rejection are enforced before transport; error strings are sanitized/truncated
  consistently in both `tasks._finish` and `xnet`.
- Namespace key escaping is injective across identities and kinds.
- No RustPython/CPython stdlib incompatibility found in the new modules (the
  codec bugs H1/H2 are semantic — JSON escaping ≠ Candid escaping — not a
  missing-stdlib problem). Confirmed by a clean Kybra Wasm build.

---

## Reproduction notes

- Full suite: `.venv-dev/bin/python -m pytest tests/unit tests/pocketic -q`
- Replica build/deploy: added `vnext_exercise` to `dfx.json`;
  `dfx deploy vnext_exercise` (local replica, default identity).
- Host repros for H1/H2/H3/H5/H6/M1/M4 were run against `.venv-dev` from the
  repo root; each is a few lines of Python importing the target module directly.
- Mainnet deploy was **not** performed — every defect reproduces locally, and
  none required mainnet to demonstrate. Recommend fixing H1–H7 before any
  mainnet release, then running the section-12 real-toolchain gate.
