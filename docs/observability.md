# Observability — seeing into a live canister

## Logging (`pyre.log`)

```python
from pyre import log

@app.post("/items", update=True)
def create(req):
    log.info("item created", id=item_id, caller=req.caller)
    ...
    log.exception("upstream sync failed", exc, url=SUPA_URL)
```

Structured, levelled (`debug/info/warning/error`), and retrievable from a
**running** canister without redeploying:

```bash
dfx canister logs rest_api                 # local
dfx canister logs rest_api --network ic    # mainnet
```

Under `pyre dev` the same lines go to stderr. `log.set_level("warning")`
silences the chatter in production.

Two rules:

- **Bounded buffer.** The IC keeps a rolling canister-log window — logs are
  diagnostics, not an audit trail. Durable records belong in `pyre.data`.
- **Never log secrets.** Same rule as canister state. Logs are
  controller-visible by default and can be made public
  (`dfx canister update-settings --log-visibility public`).

## Inspecting a live canister

| What | How |
|---|---|
| Cycle balance, memory, module hash | `dfx canister status <name> [--network ic]` |
| Recent log lines | `dfx canister logs <name> [--network ic]` |
| Per-request instruction cost | `dfx canister call <name> pyre_perf_probe` (templates ship this probe) |
| Is it serving certified responses? | `curl -sI https://<id>.icp0.io/health \| grep -i ic-certificate` |
| Independent response verification | `python scripts/verify_certification.py <url> <canister-id>` |

A missing `IC-Certificate` header on a certified route is the tell that a
canister is running stale code — check `module hash` in `dfx canister
status` against your local build (the v1.0 partial-deploy lesson).

## Cost watch

Idle burn scales with memory size (measured ~2.1B cycles/day at ~48 MB).
`make budget-gate` fails CI on instruction, WASM-size, and idle-burn
regressions, so growth shows up in review rather than on your cycle bill.
