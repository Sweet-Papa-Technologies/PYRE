# __PROJECT_NAME__

A [PYRE](https://github.com/) app for the Internet Computer.

## Iterate locally (no replica)

```bash
pyre dev src/app.py
curl http://127.0.0.1:8000/health
```

## Deploy to a local replica

Requires the PYRE toolchain venv (Python 3.10.7 + `kybra` + `pyre-icp`) to be
active, and dfx installed.

```bash
dfx start --background
dfx deploy
curl "http://$(dfx canister id __PROJECT_NAME__).localhost:4943/health"
```

## Deploy to mainnet

```bash
dfx deploy --network ic
```

## The two ICP concepts you need

- **`update=True`** — GET routes run as fast read-only *queries*; anything
  that writes `pyre.kv` or calls out over HTTPS needs an *update* call.
  POST/PUT/DELETE and async handlers are updates automatically.
- **`transform`** — outbound HTTPS responses are fetched independently by
  every replica; the transform strips volatile headers (Date, Set-Cookie, …)
  so replicas agree. `pyre.compat.urllib_request` applies a safe default.
