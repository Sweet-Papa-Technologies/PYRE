
## v1.1 mainnet verification run (2026-07-03)

No new funding: run paid from the existing ledger (8.909T at start;
0.15T top-up per canister before upgrades, per the v1.0 lesson).

**Upgrades:** rest_api + food_tracker upgraded on ic; module hashes
verified against the local .dfx/ic builds (stale-code check now standard
after v1.0's partial-deploy incident). phase1_spike deliberately not
upgraded (framework-free; nothing changed for it).

**Phase-3 sign gate on mainnet — 5/5 PASS:**
- 7me34 (rest_api) issued ES256K JWTs signed by the REAL production
  key_1 threshold key; public key 022fe8ee5902bf4a…
- All 3 signatures verified EXTERNALLY (scripts/verify_signature.py,
  pure secp256k1 math, no IC trust involved); tampered JWT rejected.
- **Measured cost: 26,190,813,124 cycles per attest** (incl. the update
  envelope) — within 0.2% of the published ~26.15B sign fee. ≈ $0.035
  per signature: fine for attestations/JWT issuance, not for per-request
  hot paths.
- Certified surface intact post-upgrade: /health (rest_api) and /summary
  (food_tracker) both HTTP 200 via icp0.io AND pass the official
  @dfinity/response-verification BLS check against the NNS root key.

**Phase-4 adapter fan-out gate:** routes live in Example B
(/supa/write /supa/rows/{id} /supa/read; config gitignored,
supa_config.example.py committed). BLOCKED at run time by a Supabase
SaaS outage (project DNS not resolving from any public resolver);
the local replica exercised the code path and failed cleanly with the
typed OutcallFailed DNS error — the error path works. Gate runs as soon
as Supabase recovers: local smoke → upgrade outbound on ic → one
/supa/write → /supa/rows/{id} must return count=1 (13 amplified
upserts converging to one row).
