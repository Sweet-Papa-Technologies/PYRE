# pyre.oidc — "Log in with Google" (OIDC ID tokens), verified in-canister

`pyre.oidc` verifies third-party OpenID Connect **ID tokens** — RS256- or
ES256-signed JWTs, the kind Google Identity Services hands your frontend —
entirely inside the canister. No trusted middleman server, no oracle: the
canister checks Google's RSA signature itself.

```python
from pyre import oidc

verifier = oidc.OidcVerifier(
    oidc.google(client_id="1234-abc.apps.googleusercontent.com"))

@app.post("/login", update=True)      # update: may outcall for JWKS (once)
async def login(req):
    claims = await verifier.verify(req.json()["id_token"])
    # claims["sub"]   — the user's stable Google id (use THIS as identity)
    # claims["email"], claims["email_verified"], claims["name"], ...
    session_id = await issue_session(claims["sub"])   # your session store
    return Response.json({"session": session_id})
```

`verify()` is awaitable in `async def` handlers and yieldable in
generator-style handlers, exactly like `urlopen` and `pyre.sign`.

On failure it raises a typed `OidcError` subclass (all `PyreError`s, all
carrying `status = 401` except `JwksFetchError` = 502):

| Error | Meaning |
|---|---|
| `MalformedToken` | not a well-formed 3-part base64url JWT |
| `UnsupportedAlgorithm` | `alg` not RS256/ES256 — `none` and HMAC rejected by design |
| `UnknownSigningKey` | no JWK matched the token's `kid`, even after one refresh |
| `InvalidSignature` | signature does not verify against the provider key |
| `InvalidClaims` | wrong `iss`/`aud`, expired, or not-yet-valid |
| `JwksFetchError` | the provider's JWKS endpoint could not be fetched |

## How it stays cheap: the JWKS cache

Verifying a signature needs the provider's current public keys (its JWKS).
Fetching those is an HTTPS outcall — and an outcall fans out to every
replica (~13× on mainnet). If every login refetched the JWKS, that tax
would land on every login. It does not:

- The JWKS is cached in a `pyre.data` collection (over `pyre.kv`, i.e.
  **stable memory — it survives upgrades**).
- A steady-state login performs **zero outcalls**: pure in-canister RSA
  math against the cached key. This is query-safe, sync, and costs ~30M
  instructions (~0.6% of a query's budget).
- The only outcall is the **first login after a provider key rotation**:
  an unknown `kid` triggers exactly one refresh, then the token is
  re-checked. Unknown even after refresh → `UnknownSigningKey` (no loop).

## The JWKS determinism transform (do not skip this)

Every canister using `pyre.oidc` must register the JWKS transform under
its Candid name (`oidc.JWKS_TRANSFORM`):

```python
from kybra import query
from kybra.canisters.management import HttpResponse, HttpTransformArgs
from pyre import oidc

@query
def pyre_oidc_jwks_transform(args: HttpTransformArgs) -> HttpResponse:
    return oidc.transform_jwks_response(args["response"])
```

Why the default header-stripping transform is not enough: **Google serves
the same key set with different JSON byte-serializations** (per-backend
field ordering — measured directly: 12 consecutive fetches of
`oauth2/v3/certs` returned byte-distinct bodies of identical logical
content). On mainnet each replica fetches independently, so replicas can
receive different bytes and the outcall would *intermittently* fail
consensus — while looking perfectly fine on a 1-node local replica.

`transform_jwks_response` canonicalizes the body on every replica: keeps
the content-type/content-encoding header allowlist, sorts the `keys` list
by `kid`, and re-serializes with sorted object keys and canonical
separators. Verified: every observed upstream variant maps to identical
bytes, on host and in-canister.

## Providers are data, not code

```python
class Provider:  issuer, jwks_uri, audience, name
```

- `oidc.google(client_id)` — Google. Accepts both historical `iss` forms
  (`https://accounts.google.com` and `accounts.google.com`).
- `oidc.generic(issuer, jwks_uri, client_id, name=None)` — any
  standards-compliant OIDC issuer. GitHub Actions OIDC, for example:

```python
gha = oidc.generic(
    issuer="https://token.actions.githubusercontent.com",
    jwks_uri="https://token.actions.githubusercontent.com/.well-known/jwks",
    client_id="https://github.com/your-org",   # your workflow's audience
    name="github-actions",
)
claims = await oidc.OidcVerifier(gha).verify(token)
```

Nothing about Google is special-cased in the verify path — a new provider
is three URLs/strings. Each provider's keys are cached independently (a
key from one issuer can never verify a token "for" another, even with a
colliding `kid`).

`audience` is **mandatory** — it is your OAuth client id, and the token's
`aud` must match. Without that check, a valid Google token minted for any
other app in the world would log into yours. `Provider` refuses to
construct without it.

## Security notes

- **An ID token proves identity, not session.** Verify once at login,
  then issue your own session (a crypto-random id from
  `await pyre.random.raw_bytes()` mapped to the identity in `pyre.data`).
  Do not re-verify a Google token per request, and do not threshold-sign
  sessions (~$0.035/signature — see `docs/secrets-and-outcalls.md`).
- Claim checks run against **consensus time** (`pyre.time`) with a 60 s
  clock-skew allowance (`OidcVerifier(..., leeway=...)`). Good enough for
  `exp`/`nbf`; don't expect sub-second semantics.
- `alg` confusion is structurally rejected: only RS256/ES256 are
  dispatched, `none`/HS256 raise `UnsupportedAlgorithm` before any key is
  touched.
- The client id is **public**, not a secret — it ships in your frontend.
  The classic setup pain is origin mismatch: register your canister URL /
  custom domain as an authorized JavaScript origin in Google Cloud
  Console early.

## Backends

In-canister, RS256/ES256 dispatch to the `_pyre_native` Rust extension
(audited RustCrypto crates `rsa` 0.9.6 / `p256` 0.13.2, verification-only —
entropy-free, no getrandom feature anywhere). Build with:

    scripts/build_native.sh <canister> --install

On host CPython (`pyre dev`, unit tests) the same Python surface uses the
`cryptography` package (dev-only shim, like `pyre.crypto`'s). Measured
in-canister cost: raw RS256 verify ≈ 21M instructions; the full
decode+verify+claims path ≈ 30M — ~0.6% of a query's instruction budget.

## What has been proven, honestly (Phase-B gate, 2026-07-03)

Proven on a local replica (`examples/oidc_spike`, across four upgrades):

- RS256 + ES256 known-answer verification through `_pyre_native`, with
  tampered/wrong-message negatives rejected.
- The full `OidcVerifier` path against a seeded cache — the zero-outcall
  steady-state login — accepting valid RS256/ES256 tokens and rejecting
  expired / wrong-audience / tampered / unknown-kid tokens.
- A live outcall to Google's real `oauth2/v3/certs` (HTTP 200, 4 real
  keys) — and a forged token claiming a *real* Google `kid` was rejected
  with `InvalidSignature` after the canister refreshed and parsed
  Google's real 2048-bit key: real key material is parsed and used.
- JWKS cache persistence across upgrades (stable memory), refresh-once on
  kid miss, and byte-identical canonicalized JWKS bodies across repeated
  fetches (the determinism transform above).

Not yet proven, and why:

- **A token Google actually signed.** Minting one requires an interactive
  browser OAuth flow — there is nothing headless that produces a real
  Google signature. The crypto is identical regardless of who minted the
  token; to close the gap yourself in ~1 minute: open
  <https://developers.google.com/oauthplayground>, authorize the openid +
  email scopes, "Exchange authorization code for tokens", copy the
  `id_token`, then
  `dfx canister call oidc_spike verify_token '("<id_token>", "407408718192.apps.googleusercontent.com")'`
  (that audience is the OAuth Playground's own client id). Expected:
  `OK {...your claims...}`.
- **13-replica behavior** (mainnet): per-verify cycle cost and the
  cross-replica JWKS fetch. Both ride the next funded mainnet run.

## The fallback that wasn't needed

The PyreBlog spec (§4 Phase B) treats OIDC-in-canister as a hard gate
with a designed "out": if the RSA crates wouldn't compile to the Kybra
WASM target, blew the size budget, or couldn't verify a real token, the
plan was to drop to **Internet Identity** — II yields a verified
principal in `req.caller` with no external signature verification at all,
at the cost of a more web3-flavored login UX. The gate **passed** (crates
compiled first try at ~+124 KB raw / +22 KB gz, ~0.44%), so the Google
path shipped. If you *prefer* II for your own app, it composes with the
same session pattern above: swap "verify ID token" for "read the II
principal", keep everything else.
