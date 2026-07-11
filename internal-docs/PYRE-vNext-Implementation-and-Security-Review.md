# PYRE vNext Implementation and Security Review

**Reviewed:** July 11, 2026  
**Specification:** `PYRE-vNext-Requirements-and-Technical-Spec.md`  
**Host verification:** 412 tests passed in one process; no failures/skips  
**Real Kybra/PocketIC status:** not executable in the current sandbox

## Review conclusion

Every specified vNext product area has an implementation, tests, documentation,
and explicit failure semantics. The review found and corrected issues that were
not visible in the original happy-path suite:

- canonical principal Base32 spellings were not enforced;
- Candid aliases did not support forward resolution/cycle checking;
- default xnet decoding returned unvalidated Candid text;
- task decorators could write/schedule before stable-memory binding;
- async tasks were not connected to PYRE's generator pump;
- `queue_one`/`allow` overlap state was incomplete;
- orphaned tasks were omitted from deterministic listings;
- large range responses reassembled the entire asset;
- old asset generations were not queued for bounded GC;
- global and namespace asset quotas were conflated;
- asset GC did not filter old generations by namespace;
- repeated finalized upload sessions conflicted;
- generalized finalization copied every chunk before publication;
- audit treated pinned unknown packages as implicitly clean;
- audit omitted native/non-pure/RustPython-gap/plaintext checks;
- missing audit input paths returned a false clean result;
- analytics constructors allocated input before enforcing limits;
- pivots could silently collide after stringifying column values;
- generated examples bypassed the lifecycle coordinator;
- generated Python caches could leak into wheels.

All of the above now have regression tests.

## Requirement coverage by area

| Area | Implemented verification |
|---|---|
| Architecture | Opt-in modules; reserved basenames; one stable map; versioned namespaces; deterministic lifecycle; full/slim packages |
| Foundation | Injectable plain-Python adapter; real Kybra adapter; bounded namespace helper; lifecycle ordering/failure tests |
| Testing | In-process gateway client; caller selection; yielded-call stubbing; content-addressed build cache; offline PocketIC controls; exact real-toolchain guidance |
| Audit | Stable JSON/exit codes; pins/URLs/editables; unknown/incompatible database; native files/wheels; non-pure metadata; host imports; RustPython gaps; footguns; secret literals; source size |
| Tasks | Durable interval/once records; controls; restoration; aliases/orphans; catch-up; all overlap modes; async pump; bounded supervisor; sanitized errors |
| Candid | Bounded parser; source locations; opts/vectors/records/variants/aliases; forward/cycle checks; deterministic generation; source hash/version; typed value validation/decoding |
| Xnet | Canonical principal validation; update honesty; typed methods; request/reply guards; cycles; notify; no retry; sanitized rejection; replaceable transport |
| Assets | Legacy compatibility reader; resumable immutable chunks; verified atomic manifest publication; three quota levels; ranges; >1.8 MB streaming; bounded delete/GC; public callback security |
| Analytics | Pure Python; immutable deterministic operations; pre-allocation cardinality limits; null/NaN rules; bounded batches; required host benchmarks |
| Documentation | Concept/API/security/upgrade guides, agent guidance, packaging decision, and manual test guide |

## Security properties checked

- Framework identifiers, stable keys, methods, task names, lifecycle names,
  principals, Candid structures, payloads, paths, headers, ranges, tokens, and
  cardinalities have explicit bounds.
- Query mutations/outcalls are rejected before platform contact.
- Remote/task error strings are sanitized and truncated.
- Bearer comparison uses `hmac.compare_digest` where available and bearer values
  are never logged.
- Streaming tokens can address only validated public asset coordinates; the
  immutable generation must still be live. Streaming is explicitly uncertified
  and unsupported for private media.
- Large assets are never reassembled for streaming/ranges. Finalization hashes
  incrementally and publishes with one manifest-pointer write. Asset manifests
  are limited to 512 chunks so verification cannot grow without a configured
  bound.
- Deletion removes the live pointer first; physical deletion and old-generation
  GC are resumable and namespace-scoped.
- Audit inspection uses AST, filesystem entries, and `importlib.metadata`; it
  does not import inspected distributions.
- Test-only Kybra/PocketIC/BLAKE3 fallbacks are labeled and excluded from claims
  about cryptography, Wasm, consensus, BLS, cycles, or instructions.

## Deliberately unsupported or deferred items

These match the specification's MVP/P2 boundaries and are not incomplete MVP
implementations:

- task cron syntax;
- automatic xnet/update retries;
- composite-query optimization;
- arbitrary first-class Candid function/service values;
- runtime downloading/parsing of untrusted `.did` files;
- private/authenticated streaming;
- certified streaming;
- multiple HTTP byte ranges;
- cross-canister asset transfer;
- pandas/NumPy compatibility;
- online vulnerability lookup when no reviewed client/source is configured.

## Verification evidence

```text
python3 -m pytest tests/unit tests/pocketic -q
412 passed

make e2e
PASS (deterministic offline mode)

make budget-gate
PASS (explicit MOCK source/instruction proxies)

full wheel import: PASS
slim wheel import/exclusions: PASS
wheel cache artifacts: none
```

The full and slim wheel-size exception is explicitly approved and recorded in
`DECISIONS.md`.

## Remaining release proof—environmental, not represented as passed

The current workspace does not contain a working Kybra 0.7.1 Python package,
`pocket-ic`/`ic-py`, or built Wasm, and network installation is unavailable.
Therefore this review does **not** claim that the following real-platform gates
ran here:

- Kybra static analysis/compilation of every new module and callback;
- real timer callbacks across an awaited raw call;
- two-canister PocketIC xnet mutation/read;
- Wasm upgrade restoration for tasks/assets;
- gateway streaming of the >1.8 MB asset against a replica;
- real Wasm size, instruction, memory, idle-burn, or cycle deltas.

These are release gates, not safely replaceable by mocks. Section 12 of
`PYRE-vNext-Manual-Testing-Guide.md` gives the exact commands and expected
non-`MOCK` evidence. A release should not be labeled fully platform-verified
until that section passes with the pinned toolchain.

