# Candid generation and cross-canister calls

Keep parsing on the host and generated metadata in the canister:

```bash
pyre candid check interfaces/counter.did
pyre candid generate interfaces/counter.did --name CounterService \
  --output src/generated/counter_service.py
```

Output is deterministic and records the source SHA-256 and generator version.
The MVP supports primitives, opts, vectors, records, variants, aliases, service
methods, query, and oneway. First-class function/service values, imports, and
runtime `.did` downloading are unsupported.

```python
from pyre import xnet
from generated.counter_service import CounterService

counter = xnet.CanisterClient("aaaaa-aa", CounterService)
value = await counter.call("increment", 1)
```

Calls validate arguments and principals, reject query context, attach zero
cycles by default, and guard requests/replies at 1,900,000 bytes. `notify` is
explicit fire-and-forget. Update calls are never retried automatically and work
before and after `await` is not one atomic transaction. Remote messages are
sanitized and truncated. Use a replaceable transport for unit tests.

Regenerate clients whenever the `.did` changes and review the diff. Malformed or
unexpected replies raise `CandidDecodeError` naming the method.

The parser and generator are original PYRE code distributed under this
repository's MIT license. They do not copy or import an `ic-py` grammar.
