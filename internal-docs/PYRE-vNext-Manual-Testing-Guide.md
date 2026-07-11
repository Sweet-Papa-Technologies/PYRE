# PYRE vNext Manual Testing Guide

This guide manually verifies the vNext lifecycle, platform adapter, namespaces,
testing client, audit command, persistent tasks, Candid generation, xnet,
generalized assets/streaming, packaging profiles, and experimental analytics.

The commands assume the repository root as the working directory.

## 1. Understand the two verification modes

PYRE uses real tools whenever they are installed and built artifacts exist.
Otherwise its repository gates use deterministic offline fallbacks.

- Output beginning with `MOCK` verifies PYRE application logic, stable-KV
  emulation, lifecycle behavior, parsing, limits, and gateway wiring.
- Mock output does **not** prove Wasm compilation, replica consensus, BLS
  certification, real instruction/cycle usage, or Kybra protocol compatibility.
- A release should run both the offline checks and the real-toolchain checks in
  section 12.

No fallback code is imported by ordinary canister applications. Kybra/PocketIC
stubs live in `pyre.testing` and the test suite only.

## 2. One-command offline acceptance

```bash
make test
make pocketic
make e2e
make budget-gate
```

Expected in an environment without Kybra/PocketIC:

- Unit tests report no failures or dependency-related skips.
- PocketIC output says `offline deterministic fallback (not Wasm/replica)`.
- E2E reports routing, certification wiring, update persistence, upgrade, and
  error handling as `PASS`.
- Budget output is labeled `MOCK` and passes the source/instruction proxies.

To run everything in one pytest process and detect leaked global state:

```bash
python3 -m pytest tests/unit tests/pocketic -q
```

## 3. Lifecycle coordinator and stable namespaces

Run focused tests:

```bash
python3 -m pytest \
  tests/unit/test_lifecycle.py \
  tests/unit/test_namespace.py \
  tests/unit/test_platform.py -q
```

Expected coverage:

- `app.recertify()` happens before restoration hooks.
- Hooks run by `(order, name)` and duplicate names fail.
- Required failures propagate; optional failures log and continue.
- Keys resemble `__pyre:tasks:1:record:job` and `:` inside identities is escaped.
- Prefix deletion never touches application keys.
- Host IC operations raise `PlatformUnavailable` until an adapter is installed.

Manual host probe:

```bash
python3 - <<'PY'
from pyre._namespace import framework_key
from pyre import _platform

print(framework_key("tasks", 1, "record", "daily:refresh"))
try:
    _platform.call_raw("aaaaa-aa", "ping", b"")
except _platform.PlatformUnavailable as error:
    print(error.code, str(error))
PY
```

Expected key: `__pyre:tasks:1:record:daily%3Arefresh`.

## 4. Public testing client and toolchain diagnostics

```bash
python3 - <<'PY'
from pyre import App
from pyre.testing import PyreTestClient, real_toolchain_problems

app = App()

@app.get("/caller")
def caller(request):
    return {"caller": request.caller}

client = PyreTestClient.from_app(app)
assert client.get("/caller").json() == {"caller": "2vxsx-fae"}
assert client.with_caller("aaaaa-aa").get("/caller").json() == {"caller": "aaaaa-aa"}
print("testing client: PASS")
print("\n".join(real_toolchain_problems()) or "real toolchain available")
PY
```

The response object exposes `status_code`, `headers`, `body`, `text`, `json()`,
and `raw`. Query responses with `upgrade=True` are automatically reissued as
updates, matching the HTTP gateway.

Build-cache behavior:

```bash
python3 -m pytest tests/unit/test_testing_public_api.py \
  -k 'wasm_build_cache or toolchain' -q
```

The first build is a miss, the second identical build is a hit, source changes
invalidate it, and `no_cache=True` rebuilds.

## 5. Dependency and source audit

Clean application audit:

```bash
python3 -m pyre.cli audit --canister examples/rest_api/src --format json
echo $?
```

Expected: JSON schema `1`, status `pass`, source byte count, and exit `0`.

Create intentionally unsafe inputs:

```bash
tmp="$(mktemp -d)"
printf 'numpy==2.0.0\nunknown-lib==1.0\n' > "$tmp/requirements.txt"
printf 'import socket\nAPI_TOKEN = "plaintext"\n' > "$tmp/app.py"
printf 'native' > "$tmp/extension.so"
python3 -m pyre.cli audit "$tmp/requirements.txt" \
  --canister "$tmp" --format json --strict
echo "exit=$?"
rm -rf "$tmp"
```

Expected findings include incompatible/unknown packages, RustPython gap,
plaintext-secret heuristic, and native extension. Definite incompatibility exits
`2`; strict warnings alone exit `1`; missing input paths exit `3`. The audit uses
distribution metadata and file lists and never imports inspected package code.

## 6. Persistent tasks

Run the complete fake-time scheduler suite:

```bash
python3 -m pytest tests/unit/test_tasks.py -q
```

It covers interval/one-shot execution, controls, update honesty, sanitized
failures, upgrade restoration, skip/run-once catch-up, orphan visibility,
bounded batches, async pumping, `queue_one`, and `allow` overlap.

Minimal application registration:

```python
from pyre import tasks

@tasks.every(seconds=300, name="refresh_prices",
             overlap="skip", catch_up="run_once")
async def refresh_prices():
    # Await deterministic outcalls/xnet here. Make side effects idempotent.
    ...

@tasks.after(seconds=30, name="warm_once")
def warm_once():
    ...
```

Controls (call them only from authenticated update routes):

```python
tasks.pause("refresh_prices")
tasks.resume("refresh_prices")
tasks.cancel("warm_once")
result = tasks.run_now("refresh_prices")
state = tasks.status("refresh_prices")
all_states = tasks.list()
```

Important manual checks:

- `tasks.list()` is name-sorted and includes orphaned durable definitions.
- No record contains a native timer handle.
- Removing a definition and upgrading marks it `orphaned`.
- Rename before restoration with `tasks.rename("old", "new")`.
- Execution is not exactly once; callbacks must be idempotent.

## 7. Candid parser and deterministic code generation

```bash
tmp="$(mktemp -d)"
cat > "$tmp/counter.did" <<'DID'
type Result = variant { ok : nat64; err : text };
service : {
  get : () -> (nat64) query;
  increment : (nat8) -> (Result);
}
DID

python3 -m pyre.cli candid check "$tmp/counter.did"
python3 -m pyre.cli candid generate "$tmp/counter.did" \
  --name CounterService --output "$tmp/counter.py"
cp "$tmp/counter.py" "$tmp/first.py"
python3 -m pyre.cli candid generate "$tmp/counter.did" \
  --name CounterService --output "$tmp/counter.py"
cmp "$tmp/first.py" "$tmp/counter.py"
grep -E 'sha256|GENERATOR|CounterService' "$tmp/counter.py"
rm -rf "$tmp"
```

Expected: check succeeds, both generated files are byte-identical, and output
contains a source SHA-256 plus generator version. Negative parser tests:

```bash
python3 -m pytest tests/unit/test_candid_parser.py \
  tests/unit/test_candid_codegen.py tests/unit/test_candid_runtime.py -q
```

These verify line/column/token diagnostics, configurable size/depth/field/alias
limits, forward aliases, cycle rejection, nested values, and integer bounds.

The parser/generator is original PYRE code under this repository's MIT license;
it does not copy or import `ic-py` grammar/code.

## 8. Cross-canister client (`pyre.xnet`)

```python
from generated.counter import CounterService
from pyre.xnet import CanisterClient

counter = CanisterClient("aaaaa-aa", CounterService)
result = await counter.call("increment", 1, cycles=0)
counter.notify("increment", 1)  # explicit fire-and-forget
```

Host failure/transport matrix:

```bash
python3 -m pytest tests/unit/test_xnet.py -q
```

Expected coverage includes canonical principal CRC/Base32 validation, unknown
methods, query-context rejection before transport, request/reply 1.9 MB guards,
integer/record/variant validation, explicit cycles, notify, sanitized rejection,
and typed textual-Candid decoding.

Never retry arbitrary update calls automatically. A successful remote update and
subsequent local failure are not one atomic transaction.

## 9. Generalized assets, ranges, streaming, and GC

Mount a store and authenticated management routes:

```python
from pyre import assets

media = assets.AssetStore(
    "media",
    max_asset_bytes=100_000_000,
    max_namespace_bytes=300_000_000,
    max_total_bytes=500_000_000,
)
assets.admin_routes(app, media, token_check="replace-with-deploy-secret")

@app.get("/media/{asset_id}")
def media_response(request):
    return media.response(request.path_params["asset_id"], request=request,
                          stream=True)
```

Upload and inspect:

```bash
python3 - <<'PY'
with open('/tmp/pyre-large.bin', 'wb') as handle:
    handle.write((b'PYRE-LARGE-ASSET-' * 120000)[:1900001])
PY

pyre assets push /tmp/pyre-large.bin --namespace media \
  --url http://127.0.0.1:8000 --token replace-with-deploy-secret
pyre assets list --url http://127.0.0.1:8000 --token replace-with-deploy-secret
pyre assets verify pyre-large.bin --url http://127.0.0.1:8000 \
  --token replace-with-deploy-secret
curl -i -H 'Range: bytes=500-4099' http://127.0.0.1:8000/media/pyre-large.bin
pyre assets delete pyre-large.bin --url http://127.0.0.1:8000 \
  --token replace-with-deploy-secret --batch-size 10
```

Expected upload output includes uploaded/wire/skipped bytes, chunks, SHA-256,
namespace, and asset ID. Range returns `206` and `Content-Range`; multiple ranges
return `416`. Deletion removes the live pointer first and reclaims chunks in
bounded batches. Replacing content queues the old immutable generation for GC.

Run security and >1.8 MB tests:

```bash
python3 -m pytest tests/unit/test_asset_store.py tests/unit/test_assets.py \
  tests/unit/test_assets_cli.py tests/unit/test_static.py -q
```

Streaming is public and currently uncertified. Do not use the callback for
private/authenticated media; it does not replay middleware context. Refresh old
generated `main.py` files before streaming so they expose
`pyre_http_streaming_callback`.

## 10. Experimental analytics

```bash
python3 - <<'PY'
from pyre.analytics import Table, col

records = [
    {"symbol": "A", "price": 2, "size": 5},
    {"symbol": "A", "price": 4, "size": 1},
    {"symbol": "B", "price": 3, "size": 2},
]
summary = (Table.from_records(records)
    .filter(col("price") > 0)
    .group_by("symbol")
    .aggregate(avg_price=("price", "mean"), volume=("size", "sum"))
    .sort_by("symbol"))
print(summary.to_json())
print(summary.record_batches(batch_size=1))
PY
```

Expected A average `3.0`, volume `6`; B average `3.0`, volume `2`.

```bash
python3 -m pytest tests/unit/test_analytics.py -q
```

This checks immutable transformations, deterministic sorting/grouping, null
semantics, bounded generator ingestion, joins, pivot collisions/cardinality,
rolling operations, and explicit persistence batches. This API is experimental
and not pandas-compatible. Use integer fixed-point or `Decimal` for money.

## 11. Full and slim packaging profiles

```bash
rm -rf /tmp/pyre-full /tmp/pyre-slim build
bash scripts/build_wheel.sh full /tmp/pyre-full
rm -rf build
bash scripts/build_wheel.sh slim /tmp/pyre-slim
unzip -l /tmp/pyre-full/*.whl | grep 'pyre/tasks.py'
if unzip -l /tmp/pyre-slim/*.whl | grep 'pyre/tasks.py'; then
  echo 'FAIL: tasks unexpectedly present in slim wheel'; exit 1
else
  echo 'PASS: tasks excluded from slim wheel'
fi
```

The full wheel must contain every vNext module. The slim wheel excludes tasks,
assets, analytics, Candid/xnet, testing, and host audit/codegen without deleting
repository sources. Neither wheel should contain `.pyc` or `__pycache__` files.

## 12. Real Kybra + PocketIC + local-replica release gate

Install only in dedicated environments (network required once):

```bash
~/.pyenv/versions/3.10.7/bin/python -m venv venv
venv/bin/pip install kybra==0.7.1 .
venv/bin/python -m kybra install-dfx-extension

~/.pyenv/versions/3.10.7/bin/python -m venv .venv-dev
.venv-dev/bin/pip install pytest pocket-ic==3.1.2 ecdsa cryptography -e .
eval "$(bash scripts/pocketic_setup.sh | tail -1)"
```

Build and run real gates:

```bash
source venv/bin/activate
dfx start --background --clean
dfx deploy
make pocketic
make e2e
make budget-gate
make budgets
```

Confirm PocketIC output does **not** contain `offline deterministic fallback`
and budget output does not contain `MOCK`. Then manually test:

1. Schedule a task, advance PocketIC time, upgrade Wasm, tick, and confirm one
   execution with the selected catch-up policy.
2. Install two fixture canisters; call a generated xnet update, read the remote
   state afterward, then force local post-call failure to demonstrate
   non-atomicity.
3. Upload the 1,900,001-byte asset, fetch through the HTTP gateway, follow every
   callback token, and compare SHA-256 with the source.
4. Check `dfx canister status` memory/cycles and `pyre_perf_probe` instruction
   results against recorded real thresholds.
5. Verify certified non-streaming routes independently. Do not interpret public
   asset streaming as certified.

Stop the replica afterward:

```bash
dfx stop
```

## 13. Security review checklist

- [ ] No bearer token, private key, OIDC token, full remote reply, or task error
      is logged or persisted without bounding/redaction.
- [ ] Task and xnet side effects are idempotent; there is no implicit retry.
- [ ] Every query mutation/outcall attempt fails before platform contact.
- [ ] Candid source/value nesting, fields, aliases, integers, methods, principals,
      and payload sizes are bounded and validated.
- [ ] Asset IDs/namespaces/tokens/content types/ranges are malformed-input tested.
- [ ] Asset quota checks include per-asset, namespace, and global totals.
- [ ] Streaming remains public-only and callback tokens cannot address arbitrary
      KV keys or cross namespaces.
- [ ] Deletion and old-generation GC remain bounded.
- [ ] Audit findings are reviewed; `unknown` is never called compatible.
- [ ] Full and slim wheels contain no generated cache/native test artifacts.
- [ ] Real release output contains no `MOCK` labels.

