# Persistent tasks

`pyre.tasks` stores scheduling intent in the existing stable KV map and rebuilds
ephemeral timers after install or upgrade:

```python
from pyre import tasks

@tasks.every(seconds=300, name="refresh_prices", overlap="skip", catch_up="run_once")
def refresh_prices():
    pass
```

`every` and `after` return the original callback. Controls are `pause`,
`resume`, `cancel`, `run_now`, `status`, `list`, `rename`, and orphan-only
`purge`. Names are durable identities. Rename with `tasks.rename(old, new)`
before restoration; removed definitions become inspectable orphans.

Tasks are not exactly once. Traps, upgrades, and remote side effects can produce
observable duplicates, so callbacks should be idempotent. `skip` is the default
overlap and catch-up policy; `run_once` executes at most one missed invocation.
The supervisor handles at most 25 due tasks per wake and persists no timer IDs.
`run_now` requires update context. Cron and automatic retries are unsupported.

Never put secrets in task records or errors. Async callbacks require the
canister platform runner; no `asyncio`, threads, or host event loop is used on
chain. Schema 1 records live below `__pyre:tasks:1:` and unknown schemas fail
closed.

