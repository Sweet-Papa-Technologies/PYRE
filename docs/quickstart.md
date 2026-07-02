# Quickstart — zero to deployed in ~15 minutes

You need: macOS/Linux, [pyenv](https://github.com/pyenv/pyenv), and ~10 minutes
of build time on first deploy.

## 1. Install the toolchain

```bash
# Python 3.10.7 (Kybra's pinned interpreter version)
pyenv install 3.10.7

# dfx (the Internet Computer SDK)
DFXVM_INIT_YES=true sh -c "$(curl -fsSL https://internetcomputer.org/install.sh)"

# a project venv with pyre + kybra
~/.pyenv/versions/3.10.7/bin/python -m venv venv && source venv/bin/activate
pip install pyre-icp kybra==0.7.1
python -m kybra install-dfx-extension
```

## 2. Create and run an app — no blockchain required

```bash
pyre new myapp --template crud-kv
cd myapp
pyre dev src/app.py
```

```bash
curl -X POST -d '{"name": "apple", "qty": 3}' http://127.0.0.1:8000/items
curl http://127.0.0.1:8000/items
```

`pyre dev` is a plain local server running the same routing code the
canister runs. Outbound calls do real HTTP and log what ICP's determinism
transform would strip. Query/update rules are enforced locally so on-chain
surprises surface now, not after deploy.

## 3. Deploy to a local Internet Computer replica

```bash
dfx start --background
dfx deploy           # first build compiles the runtime — go get coffee
curl "http://$(dfx canister id myapp).localhost:4943/health"
```

That `/health` response arrives with an `IC-Certificate` header — it is
cryptographically certified, not just served (see concepts.md).

## 4. Deploy to mainnet

You need cycles (ICP's prepaid compute). Roughly $2 covers creating and
installing a canister; light traffic costs well under $1/month.

```bash
dfx identity new mydev                      # dedicated key; back up the .pem!
dfx ledger account-id --identity mydev      # send ~1 ICP here from an exchange
dfx cycles convert --amount 0.9 --network ic --identity mydev
dfx deploy --network ic --identity mydev --with-cycles 900000000000
curl "https://$(dfx canister id myapp --network ic --identity mydev).icp0.io/health"
```

Two platform facts worth knowing before you're surprised (details in
concepts.md): canister creation costs 0.5T cycles, and installing the
Python runtime needs ~0.4T in the canister — that's the ~$2. Keep the
canister topped up; `dfx canister status` shows the burn rate.
