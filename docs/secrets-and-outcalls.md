# Secrets and outcalls — a documented limitation in v1.1

**Short version: secret-bearing external API calls (calling Stripe, OpenAI,
etc. with your private API key, server-side) are NOT natively supported in
PYRE v1.1.** This page explains why honestly, and describes a self-hostable
workaround you can run today.

## Why not

Using a key in an outbound request requires the key **in plaintext in
canister memory at outcall time** — and canister memory is readable by the
node operators running your subnet. There is no configuration, encryption
trick, or framework feature that changes this in v1.1:

- **Encrypting the key in state doesn't help.** To put it in an
  `Authorization` header, the canister must decrypt it first — and the
  decrypted bytes, plus the decryption key, sit in the same observable
  memory.
- **vetKeys doesn't solve this.** vetKeys' entire premise is that the
  canister *never sees plaintext* — which is exactly what an outbound
  `Authorization: Bearer sk-...` header needs. It's the right tool for
  user-side encryption, not for this.
- **Rust extensions don't solve it either.** Rust code runs in the same
  canister memory as Python; node operators see it just the same. Rust
  extends capability, not confidentiality.

Additionally, remember that outcalls are **replicated** (~13 identical
requests per call — see [concepts.md](concepts.md), concept 2), so even
setting confidentiality aside, secret-bearing calls to rate-limited or
non-idempotent endpoints need care.

## The workaround (self-hostable, works today)

Run a **tiny stateless proxy you control** that holds the real key:

1. The proxy (a few dozen lines on any host you trust — a $4 VPS, a
   serverless function) stores the actual API key. It never touches
   canister state.
2. Your canister calls the proxy instead of the vendor API, **signing each
   request with its threshold key** (`pyre.sign`, shipping in this release)
   so the proxy can verify the request really came from *your* canister and
   refuse everyone else.
3. The proxy attaches the real key and forwards the call to the vendor.

The secret lives in exactly one place you control, never on-chain, and the
canister's signature — verifiable against its public key — is the access
control.

A **paved-path version lands in v1.2**: `pyre.secure_outcall` plus shipped,
open-source proxy software, so this becomes a config option instead of a
weekend project. In v1.1 you build the proxy yourself; PYRE gives you the
signing primitive.

For those who prefer to pay rather than operate,
**confidential-compute subnets (TEEs)** are an emerging "skip the proxy
entirely" alternative — the key stays inside a hardware enclave node
operators can't inspect. Verify current availability on ICP before
depending on it.

## Trust model — read this before deploying a proxy

**Whoever runs the proxy sees the plaintext secret.** That is the whole
trade: you've moved trust from ~13 anonymous node operators to one party
you choose. Consequences:

- **Never use one shared community proxy** holding everyone's keys — that
  would be a single honeypot with total visibility. Each user runs their
  *own* proxy (or pays a host they individually trust).
- Redundancy belongs *within your own deployment* (two instances of your
  proxy), never in a shared secret-holder.
- The v1.2 shipped proxy software follows the same model: open-source,
  self-hostable, verifies your canister's tECDSA signature — one per user.

## The existing guardrail: secrets in canister state

Independent of outcalls, canister **state** is also visible to node
providers. PYRE already guards the obvious footgun: writing a key or field
that looks like a secret (`password`, `token`, `api_key`, `private_key`,
...) to `pyre.kv` triggers a dev-time warning (`_warn_if_secret` in
`pyre/kv.py`):

    pyre kv: WARNING — 'api_key:abc' looks like a secret. Canister state is
    readable by node providers; store a hash instead (see pyre.auth docs)

Store **hashes** for anything you only need to *verify* (inbound tokens,
Basic-auth passwords — see [api.md](api.md#pyreauth)). Anything you need to
*send* in plaintext belongs in the proxy above, not in state.
