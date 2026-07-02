# Contributing to PYRE

Thanks for helping make Python on the Internet Computer feel like Python.

## Setup

```bash
make setup      # Python 3.10.7 venvs (deploy + dev), kybra, dfx extension
make test       # unit suite — fast, no replica
make start      # local replica
make deploy     # build + deploy example canisters
make e2e        # curl-level acceptance incl. certification verification
```

Read `DECISIONS.md` before touching anything CDK-adjacent — it records the
Kybra landmines (bundler basename flattening, stale `.kybra` cache, Candid
alias limits, `-> void` on system methods) that will otherwise cost you an
afternoon.

## Rules of the road

- **Pure Python only** inside `pyre/` — code must run on RustPython inside
  the canister. No C extensions, no Pydantic, no interpreter-specific
  tricks without a calibration probe (see `routing._probe_async_bits`).
- **The CDK seam stays thin.** All Kybra contact lives in the generated
  `main.py`, plus lazy imports in `outcall.py` / `certification.py` /
  `gateway.py`. Nothing else may import kybra.
- **Framework module basenames are load-bearing** (Kybra flattens them);
  adding a module means adding it to `RESERVED_BASENAMES` in `cli.py`.
- **Every feature lands with unit tests**, and anything touching the
  request path also lands in `scripts/e2e_local.sh`.
- Determinism and budget gates are release blockers, not suggestions.

## Before opening a PR

1. `make test` — all green.
2. `rm -rf .kybra && make deploy && make e2e` — all green (a clean-cache
   build catches bundler staleness your incremental build hides).
3. If you changed the framework's per-request path: `make budgets` and
   compare against the numbers in DECISIONS.md.
