// Full response-verification v2 — INCLUDING the BLS signature chain to the
// real NNS root key — using DFINITY's official verifier package. This is an
// independent implementation from both PYRE and the gateway.
//
// Usage:
//   node verify.mjs <raw-url> <canister-id>            # expect PASS
//   node verify.mjs <raw-url> <canister-id> --tamper   # flip a body byte → expect FAIL
//   node verify.mjs <raw-url> <canister-id> --stale    # verify as if 1h in the future → expect FAIL
//
// Exits 0 when the observed outcome matches the expectation, 1 otherwise.

import { verifyRequestResponsePair } from "@dfinity/response-verification";
import { IC_ROOT_KEY } from "@dfinity/agent";
import { Principal } from "@dfinity/principal";

const [url, canisterId, flag] = process.argv.slice(2);
if (!url || !canisterId) {
  console.error("usage: node verify.mjs <raw-url> <canister-id> [--tamper|--stale]");
  process.exit(1);
}
const expectFail = flag === "--tamper" || flag === "--stale";

const rootKey = Uint8Array.from(Buffer.from(IC_ROOT_KEY, "hex"));

const httpResponse = await fetch(url, { redirect: "manual" });
const body = new Uint8Array(await httpResponse.arrayBuffer());
const headers = [...httpResponse.headers.entries()];

if (flag === "--tamper") {
  body[0] = body[0] ^ 0xff; // flip a byte: certified hash must no longer match
}

const path = new URL(url).pathname + new URL(url).search;
const request = { url: path, method: "GET", headers: [], body: new Uint8Array() };
const response = { status_code: httpResponse.status, headers, body };

let currentTimeNs = BigInt(Date.now()) * 1_000_000n;
if (flag === "--stale") {
  currentTimeNs += 3_600_000_000_000n * 1_000n; // pretend it's 1h later
}
const maxCertTimeOffsetNs = 300_000_000_000n; // 5 min, per the gateway spec

try {
  const result = verifyRequestResponsePair(
    request,
    response,
    Principal.fromText(canisterId).toUint8Array(),
    currentTimeNs,
    maxCertTimeOffsetNs,
    rootKey,
    2 // minimum verification version
  );
  const version = result?.verificationVersion;
  if (expectFail) {
    console.log(`UNEXPECTED PASS (${flag}) — verifier accepted a bad response`);
    process.exit(1);
  }
  console.log(`PASS: official verifier accepted the response (v${version}, BLS chain to NNS root key OK)`);
  process.exit(0);
} catch (err) {
  if (expectFail) {
    console.log(`EXPECTED FAIL (${flag}): ${String(err?.message ?? err).slice(0, 160)}`);
    process.exit(0);
  }
  console.log(`FAIL: ${String(err?.message ?? err).slice(0, 300)}`);
  process.exit(1);
}
