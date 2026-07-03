# Troubleshooting — the landmines, pre-stepped-on

Symptoms → causes → fixes. Everything here was hit for real during PYRE's
development; deeper forensics in DECISIONS.md.

| Symptom | Cause | Fix |
|---|---|---|
| `💣 Kybra error: compilation` with no detail | Kybra 0.7.1's error reporter swallows the real message | `~/.config/kybra/0.7.1/bin/kybra_generate .kybra/<name>/py_file_names.csv main /dev/stdout 0.7.1` prints the actual error |
| `Return type annotation required` | Kybra needs annotations on every decorated method — including `-> void` on `@init`/`@post_upgrade` | Annotate it |
| Build breaks after renaming/deleting a module, or old code runs after deploy | `.kybra/<name>/python_source/` is never cleaned; stale copies mix in | `rm -rf .kybra` and rebuild |
| Your module silently replaced by a framework file | Kybra's bundler flattens every module to a top-level basename slot | Don't name files like framework/CDK modules; `pyre new`/`pyre dev` warn (`RESERVED_BASENAMES` in cli.py) |
| `The type X is used, but never defined` / duplicate type errors | Candid types can't be import-aliased or share names across modules | Import without `as`, use unique record names (Candid matches structurally) |
| Outcall fails: `Connecting to <host> failed` / timeout | Host has no IPv6 (AAAA) — replicas prefer IPv6; the platform's IPv4 fallback covers some hosts but not all | `dig AAAA <host>`; test your provider from mainnet; relay pattern in docs/adapters.md |
| `dfx deploy` hangs or dies with `error sending request for url (…/canister/…/call)`; replica port open but connections reset | Local replica wedged (stale state or half-dead process) — dfx tooling flake, not your code | `dfx killall && dfx start --clean --background` (`--clean` wipes local canister state), then redeploy |
| Need to call Stripe/OpenAI with a private API key | Not natively supported in v1.1 — the key would sit in plaintext in canister memory where node operators can read it | Self-host a tiny signed proxy that holds the key (see `docs/secrets-and-outcalls.md`); paved path (`pyre.secure_outcall`) lands in v1.2 |
| Outcall fails: `No consensus could be reached. Replicas had different responses` | Upstream response body/headers differ per replica | Use the default transform; for volatile *body* fields, a JSON-normalizing custom transform (see `examples/phase1_spike`) |
| `FakeEntropyError: uuid.uuid4() returns a CONSTANT inside a canister` (also os.urandom, secrets.*) | The interpreter has no entropy source; these APIs would silently return the same bytes forever, so pyre defuses them at import | `pyre.random.uuid4()` for ids; `await pyre.random.raw_bytes(n)` for cryptographic bytes (see `docs/random-uuid-time.md`) |
| 503 `backend_response_verification` from the gateway | An error response served from a query (uncertified), or a bad certificate | PYRE upgrades non-2xx to updates automatically — if you see this, check custom code paths; verify with `scripts/verify_certification.py` |
| `certified route must return 2xx at certification time` | A certified route errored during recertify — often an auth hook blocking it | Keep certified routes public (`exempt=`) or hook-aware |
| Install fails: `out of cycles: please top up ... additional cycles` | Runtime install needs ~0.4T cycles in-canister (creation fee was only the start) | `dfx cycles top-up <canister> 400000000000 --network ic` |
| `Creating a canister requires a fee of 500_000_000_000` | Creation fee is 0.5T (not the older 0.1T) | `--with-cycles 900000000000` per canister is a comfortable floor |
| Deleted a canister and its cycles vanished | Withdrawal installs a temp wallet the canister must be able to afford | Use `make teardown-mainnet C="..."` (withdraw → confirm → delete); never delete an underfunded canister |
| `kv.set() needs update context` / `OutcallInQueryContext` | Query routes can't write or call out | `update=True` (POST/PUT/DELETE and async handlers already are) |
| Handler works in dev, misbehaves on-chain around async detection | Interpreter `co_flags` bits differ between CPython and RustPython | Already handled (`routing._probe_async_bits`); pattern to copy for any interpreter-specific probing |
| Writes are slow (~2s) | That's consensus, not a bug | Keep reads on GET/query routes; batch writes where possible |
