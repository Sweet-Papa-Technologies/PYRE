# Testing PYRE applications

`pyre.testing` is an optional host-only API. It must never be imported by
canister source. The fast mode dispatches through the real PYRE gateway without
a replica:

```python
from pyre.testing import PyreTestClient

client = PyreTestClient.from_app(app)
assert client.get("/health").status_code == 200
assert client.post("/items", json_body={"name": "pear"}).json()["name"] == "pear"
```

The client supports GET, POST, PUT, PATCH, DELETE, explicit query/update calls,
deterministic caller selection, normalized status/headers/body, and the raw
gateway response. It follows the gateway's `upgrade=True` retry automatically.
Resolve yielded calls deterministically with
`client.with_call_resolver(lambda call: {"Ok": stubbed_reply})`.

PocketIC remains the authoritative mode for stable-memory upgrades, cycles,
timers, inter-canister calls, instruction measurements, and streaming. Install
the optional `pytest`, `pocket-ic==3.1.2`, Kybra 0.7.1, Python 3.10.7, and the
PocketIC 13.0.0 server, then run `make pocketic`. Always tear down instances;
the repository fixture does this even after failures.

When those dependencies or built Wasm artifacts are absent, repository tests
automatically use `OfflinePocketICClient`. It runs real PYRE routing, gateway,
stable-KV emulation, lifecycle, streaming, and deterministic time paths without
network access. Output is labeled `MOCK`; fixed cycle/instruction figures are
regression fixtures, not measurements. It does not claim Wasm execution,
replica consensus, BLS verification, subnet behavior, or real cycle accounting.
`make pocketic`, `make e2e`, and `make budget-gate` all select this fallback but
will prefer real artifacts and dependencies whenever available.

Security note: default identities are deterministic and unsuitable as secrets.
Upgrade tests must use upgrade mode, not reinstall, when asserting persistence.
